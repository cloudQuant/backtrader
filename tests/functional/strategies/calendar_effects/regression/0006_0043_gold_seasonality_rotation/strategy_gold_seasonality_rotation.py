from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


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


def prepare_seasonality_rotation_features(df, params):
    strong_months = set(int(x) for x in params.get('strong_months', [1, 8, 9, 11, 12]))
    weak_months = set(int(x) for x in params.get('weak_months', [2, 3, 6, 7]))
    sma_window = int(params.get('sma_window', 200))
    strong_weight = float(params.get('strong_weight', 1.0))
    strong_downtrend_weight = float(params.get('strong_downtrend_weight', 0.5))
    neutral_weight = float(params.get('neutral_weight', 0.5))
    neutral_downtrend_weight = float(params.get('neutral_downtrend_weight', 0.25))
    weak_weight = float(params.get('weak_weight', 0.0))

    out = df.copy()
    out['month'] = out.index.month
    out['sma_long'] = out['close'].rolling(sma_window).mean()
    out['trend_up'] = (out['close'] > out['sma_long']).astype(float)
    out['rebalance_signal'] = (out['month'] != out['month'].shift(1)).astype(float)

    def calc_target(row):
        month = int(row['month'])
        trend_up = float(row['trend_up']) > 0.5
        if month in strong_months:
            return strong_weight if trend_up else strong_downtrend_weight
        if month in weak_months:
            return weak_weight
        return neutral_weight if trend_up else neutral_downtrend_weight

    out['target_pct'] = out.apply(calc_target, axis=1)
    out['target_pct'] = out['target_pct'].clip(lower=0.0, upper=1.0)

    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'month', 'sma_long', 'trend_up', 'rebalance_signal', 'target_pct'
    ]
    return out[cols].dropna(subset=['open', 'high', 'low', 'close', 'sma_long'])


class GoldSeasonalityRotationFeed(bt.feeds.PandasData):
    lines = ('month', 'sma_long', 'trend_up', 'rebalance_signal', 'target_pct')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month', 6), ('sma_long', 7), ('trend_up', 8), ('rebalance_signal', 9), ('target_pct', 10),
    )


class GoldSeasonalityRotationStrategy(bt.Strategy):
    params = dict(
        strong_months=[1, 8, 9, 11, 12],
        weak_months=[2, 3, 6, 7],
        sma_window=200,
        strong_weight=1.0,
        strong_downtrend_weight=0.5,
        neutral_weight=0.5,
        neutral_downtrend_weight=0.25,
        weak_weight=0.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.last_target_pct = 0.0
        self.broker_value_series = []

    def _get_target_size(self, target_notional_pct, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) / (execution_price * multiplier)
        return max(0.01, round(size, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if float(self.data.rebalance_signal[0]) <= 0.5:
            return
        target_pct = float(self.data.target_pct[0])
        target_size = self._get_target_size(target_pct)
        current_size = float(self.position.size)
        if abs(target_size - current_size) < 0.01:
            return
        if target_pct > self.last_target_pct:
            self.buy_count += 1
        elif target_pct < self.last_target_pct:
            self.sell_count += 1
        self.pending_order = self.order_target_size(target=target_size)
        self.last_target_pct = target_pct

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
