from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSET_ORDER = ['GLD', 'GDX', 'XAGUSD', 'IEF']


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    df['datetime'] = parsed
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
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


def prepare_cross_market_mr_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}

    weekly_lookback = int(params.get('weekly_lookback', 5))
    signal_delay_days = int(params.get('signal_delay_days', 1))
    gross_exposure = float(params.get('gross_exposure', 0.8))
    selection_count = int(params.get('selection_count', 1))
    rebalance_weekday = int(params.get('rebalance_weekday', 4))

    close_df = pd.DataFrame({name: frame['close'] for name, frame in aligned.items()}, index=common_index).dropna()
    aligned = {name: frame.loc[close_df.index].copy() for name, frame in aligned.items()}
    weekly_returns = close_df.pct_change(weekly_lookback)

    signal_df = aligned[ASSET_ORDER[0]][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    for asset in ASSET_ORDER:
        signal_df[f'{asset.lower()}_weekly_return'] = weekly_returns[asset]
        signal_df[f'{asset.lower()}_target'] = 0.0

    rebalance_flag = pd.Series(0.0, index=signal_df.index)
    week_period = pd.Series(signal_df.index, index=signal_df.index).dt.to_period('W-FRI')
    is_week_end = week_period != week_period.shift(-1)
    rebalance_dates = signal_df.index[is_week_end]

    for rebalance_date in rebalance_dates:
        if rebalance_date.weekday() != rebalance_weekday:
            continue
        returns_row = weekly_returns.loc[rebalance_date].dropna()
        if len(returns_row) < 2:
            continue
        ranked = returns_row.sort_values()
        n_select = max(1, min(selection_count, len(ranked) // 2))
        long_assets = list(ranked.index[:n_select])
        short_assets = list(ranked.index[-n_select:])
        target_date_loc = signal_df.index.get_loc(rebalance_date) + signal_delay_days
        if target_date_loc >= len(signal_df.index):
            continue
        target_date = signal_df.index[target_date_loc]
        long_weight = gross_exposure / 2.0 / len(long_assets)
        short_weight = -gross_exposure / 2.0 / len(short_assets)
        for asset in ASSET_ORDER:
            signal_df.at[target_date, f'{asset.lower()}_target'] = 0.0
        for asset in long_assets:
            signal_df.at[target_date, f'{asset.lower()}_target'] = long_weight
        for asset in short_assets:
            signal_df.at[target_date, f'{asset.lower()}_target'] = short_weight
        rebalance_flag.at[target_date] = 1.0

    target_cols = [f'{asset.lower()}_target' for asset in ASSET_ORDER]
    signal_df[target_cols] = signal_df[target_cols].where(rebalance_flag > 0.5).ffill().fillna(0.0)
    signal_df['rebalance_flag'] = rebalance_flag
    signal_df['signal_change'] = signal_df[target_cols].round(8).ne(signal_df[target_cols].shift(1).round(8)).any(axis=1).astype(float)

    ordered_cols = ['open', 'high', 'low', 'close', 'volume', 'openinterest']
    ordered_cols += [f'{asset.lower()}_weekly_return' for asset in ASSET_ORDER]
    ordered_cols += target_cols + ['rebalance_flag', 'signal_change']
    signal_df = signal_df[ordered_cols].dropna()
    return {'signal_df': signal_df, 'asset_frames': aligned}


class CrossMarketMRFeed(bt.feeds.PandasData):
    lines = (
        'gld_weekly_return', 'gdx_weekly_return', 'xagusd_weekly_return', 'ief_weekly_return',
        'gld_target', 'gdx_target', 'xagusd_target', 'ief_target',
        'rebalance_flag', 'signal_change',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('gld_weekly_return', 6), ('gdx_weekly_return', 7), ('xagusd_weekly_return', 8), ('ief_weekly_return', 9),
        ('gld_target', 10), ('gdx_target', 11), ('xagusd_target', 12), ('ief_target', 13),
        ('rebalance_flag', 14), ('signal_change', 15),
    )


class MeanReversionAcrossMarketsStrategy(bt.Strategy):
    params = dict(
        weekly_lookback=5,
        signal_delay_days=1,
        gross_exposure=0.8,
        selection_count=1,
        rebalance_weekday=4,
        commission_pct=0.0005,
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
        if float(self.signal_data.signal_change[0]) <= 0.5:
            return
        self.rebalance_count += 1
        target_map = {
            'GLD': float(self.signal_data.gld_target[0]),
            'GDX': float(self.signal_data.gdx_target[0]),
            'XAGUSD': float(self.signal_data.xagusd_target[0]),
            'IEF': float(self.signal_data.ief_target[0]),
        }
        for asset, target in target_map.items():
            order = self.order_target_percent(data=self.asset_data[asset], target=target)
            if order is not None:
                self.pending_orders.append(order)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [pending for pending in self.pending_orders if pending.ref != order.ref]

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
