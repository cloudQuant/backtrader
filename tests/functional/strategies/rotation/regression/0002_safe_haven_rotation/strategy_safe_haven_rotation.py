from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSET_ORDER = ['XAUUSD', 'XAGUSD', 'JPY_SAFE', 'CHF_SAFE', 'IEF']


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
    df['datetime'] = parsed
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def invert_price_frame(df):
    inverse = df.copy()
    inverse['open'] = 1.0 / df['open']
    inverse['high'] = 1.0 / df['low']
    inverse['low'] = 1.0 / df['high']
    inverse['close'] = 1.0 / df['close']
    return inverse


def prepare_rotation_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}

    transformed = {
        'XAUUSD': aligned['XAUUSD'],
        'XAGUSD': aligned['XAGUSD'],
        'JPY_SAFE': invert_price_frame(aligned['USDJPY']),
        'CHF_SAFE': invert_price_frame(aligned['USDCHF']),
        'IEF': aligned['IEF'],
    }

    close_df = pd.DataFrame({name: frame['close'] for name, frame in transformed.items()}, index=common_index).dropna()
    transformed = {name: frame.loc[close_df.index].copy() for name, frame in transformed.items()}

    momentum_periods = [int(x) for x in params.get('momentum_periods', [63, 126])]
    trend_ma_period = int(params.get('trend_ma_period', 63))
    top_n = int(params.get('top_n', 1))
    backup_asset = str(params.get('backup_asset', 'IEF'))

    returns = {period: close_df / close_df.shift(period) - 1.0 for period in momentum_periods}
    rank_scores = pd.DataFrame(0.0, index=close_df.index, columns=close_df.columns)
    for period in momentum_periods:
        period_rank = returns[period].rank(axis=1, ascending=False, method='min')
        rank_scores = rank_scores.add(period_rank, fill_value=0.0)

    trend_ma = close_df.rolling(trend_ma_period).mean()
    trend_ok = close_df > trend_ma
    month_end = close_df.index.to_series().dt.month.ne(close_df.index.to_series().shift(-1).dt.month)

    selected_assets = []
    weight_rows = []
    current_asset = None
    for dt in close_df.index:
        if not bool(month_end.loc[dt]):
            selected_assets.append(current_asset)
            weight_rows.append({asset: (1.0 if asset == current_asset else 0.0) for asset in ASSET_ORDER})
            continue

        valid = rank_scores.loc[dt].dropna().sort_values()
        chosen = None
        candidate_assets = list(valid.index[:max(top_n + 2, top_n)])
        for asset in candidate_assets:
            if bool(trend_ok.loc[dt, asset]):
                chosen = asset
                break
        if chosen is None:
            chosen = backup_asset
        current_asset = chosen
        selected_assets.append(current_asset)
        weight_rows.append({asset: (1.0 if asset == current_asset else 0.0) for asset in ASSET_ORDER})

    weights_df = pd.DataFrame(weight_rows, index=close_df.index)
    weights_df = weights_df.ffill().fillna(0.0)
    selected_series = pd.Series(selected_assets, index=close_df.index).ffill()
    rebalance_flag = selected_series.ne(selected_series.shift(1)).astype(float)

    signal_df = transformed['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['rebalance_flag'] = rebalance_flag
    signal_df['xau_weight'] = weights_df['XAUUSD']
    signal_df['xag_weight'] = weights_df['XAGUSD']
    signal_df['jpy_weight'] = weights_df['JPY_SAFE']
    signal_df['chf_weight'] = weights_df['CHF_SAFE']
    signal_df['ief_weight'] = weights_df['IEF']
    signal_df = signal_df[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'rebalance_flag', 'xau_weight', 'xag_weight', 'jpy_weight', 'chf_weight', 'ief_weight']]
    return {'signal_df': signal_df.dropna(), 'asset_frames': transformed}


class RotationSignalFeed(bt.feeds.PandasData):
    lines = ('rebalance_flag', 'xau_weight', 'xag_weight', 'jpy_weight', 'chf_weight', 'ief_weight')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('rebalance_flag', 6), ('xau_weight', 7), ('xag_weight', 8), ('jpy_weight', 9), ('chf_weight', 10), ('ief_weight', 11),
    )


class SafeHavenRotationStrategy(bt.Strategy):
    params = dict(
        momentum_periods=[63, 126],
        trend_ma_period=63,
        top_n=1,
        backup_asset='IEF',
    )

    def __init__(self):
        self.signal_data = self.datas[0]
        self.asset_data = {data._name: data for data in self.datas[1:]}
        self.pending_orders = []
        self.bar_num = 0
        self.rebalance_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal_data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_orders:
            return
        if float(self.signal_data.rebalance_flag[0]) <= 0.5:
            return
        self.rebalance_count += 1
        target_map = {
            'XAUUSD': float(self.signal_data.xau_weight[0]),
            'XAGUSD': float(self.signal_data.xag_weight[0]),
            'JPY_SAFE': float(self.signal_data.jpy_weight[0]),
            'CHF_SAFE': float(self.signal_data.chf_weight[0]),
            'IEF': float(self.signal_data.ief_weight[0]),
        }
        for symbol, target in target_map.items():
            order = self.order_target_percent(data=self.asset_data[symbol], target=target)
            if order is not None:
                self.pending_orders.append(order)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [o for o in self.pending_orders if o.ref != order.ref]

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
