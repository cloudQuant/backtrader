from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


ASSET_ORDER = ['XAUUSD', 'XAGUSD', 'XPTUSD', 'XPDUSD']


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


def prepare_rotation_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    close_df = pd.DataFrame({name: frame['close'] for name, frame in aligned.items()}, index=common_index)
    periods = [int(x) for x in params.get('roc_periods', [21, 63, 252])]
    weights = [float(x) for x in params.get('roc_weights', [0.2, 0.3, 0.5])]
    score_df = pd.DataFrame(0.0, index=common_index, columns=close_df.columns)
    for period, weight in zip(periods, weights):
        roc = (close_df - close_df.shift(period)) / close_df.shift(period) * 100.0
        score_df = score_df.add(roc * weight, fill_value=0.0)
    signal_df = pd.DataFrame(index=common_index)
    signal_df['open'] = aligned['XAUUSD']['open']
    signal_df['high'] = aligned['XAUUSD']['high']
    signal_df['low'] = aligned['XAUUSD']['low']
    signal_df['close'] = aligned['XAUUSD']['close']
    signal_df['volume'] = aligned['XAUUSD']['volume']
    signal_df['openinterest'] = aligned['XAUUSD']['openinterest']
    rebalance_flag = pd.Series(0.0, index=common_index)
    weight_df = pd.DataFrame(0.0, index=common_index, columns=close_df.columns)
    top_n = max(1, int(params.get('top_n', 1)))
    month_groups = pd.Series(common_index, index=common_index).groupby(common_index.to_period('M')).agg('last')
    rebalance_dates = pd.DatetimeIndex(month_groups.values)
    current_weights = pd.Series(0.0, index=close_df.columns)
    for dt in common_index:
        if dt in rebalance_dates and dt in score_df.index:
            day_scores = score_df.loc[dt].dropna().sort_values(ascending=False)
            current_weights = pd.Series(0.0, index=close_df.columns)
            if not day_scores.empty:
                selected = day_scores.head(top_n).index.tolist()
                for symbol in selected:
                    current_weights[symbol] = 1.0 / top_n
            rebalance_flag.loc[dt] = 1.0
        weight_df.loc[dt] = current_weights
    for symbol in close_df.columns:
        signal_df[f'{symbol.lower()}_weight'] = weight_df[symbol]
        signal_df[f'{symbol.lower()}_score'] = score_df[symbol]
    signal_df['rebalance_flag'] = rebalance_flag
    signal_df = signal_df.dropna().copy()
    aligned = {name: frame.loc[signal_df.index].copy() for name, frame in aligned.items()}
    return aligned, signal_df


class RotationSignalFeed(bt.feeds.PandasData):
    lines = (
        'xauusd_weight', 'xagusd_weight', 'xptusd_weight', 'xpdusd_weight',
        'xauusd_score', 'xagusd_score', 'xptusd_score', 'xpdusd_score',
        'rebalance_flag',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('xauusd_weight', 6), ('xagusd_weight', 7), ('xptusd_weight', 8), ('xpdusd_weight', 9),
        ('xauusd_score', 10), ('xagusd_score', 11), ('xptusd_score', 12), ('xpdusd_score', 13),
        ('rebalance_flag', 14),
    )


class MomentumRotationROCStrategy(bt.Strategy):
    params = dict(
        lot_size=1.0,
        roc_periods=[21, 63, 252],
        roc_weights=[0.2, 0.3, 0.5],
        top_n=1,
        rebalance_freq='M',
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_map = {name: self.getdatabyname(name) for name in ASSET_ORDER}
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.rebalance_count = 0
        self.broker_value_series = []

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _target_size(self, data, target_weight):
        broker_value = float(self.broker.getvalue())
        price = float(data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        raw_size = broker_value * float(self.p.lot_size) * float(target_weight) / (price * multiplier)
        return round(raw_size, 2)

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        if float(self.signal.rebalance_flag[0]) <= 0.5:
            return
        self.rebalance_count += 1
        for symbol in ASSET_ORDER:
            data = self.asset_map[symbol]
            target_weight = float(getattr(self.signal, f'{symbol.lower()}_weight')[0])
            current_size = float(self.getposition(data).size)
            target_size = self._target_size(data, target_weight)
            order = self.order_target_size(data=data, target=target_size)
            self._submit(order)
            if order is not None:
                if target_size > current_size:
                    self.buy_count += 1
                elif target_size < current_size:
                    self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)
