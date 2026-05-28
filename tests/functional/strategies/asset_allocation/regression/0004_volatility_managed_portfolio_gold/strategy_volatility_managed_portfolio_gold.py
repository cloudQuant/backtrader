from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
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


def prepare_volatility_managed_features(gold_df, params):
    out = gold_df.copy()
    vol_window = int(params.get('vol_window', 20))
    target_vol = float(params.get('target_vol', 0.15))
    max_weight = float(params.get('max_weight', 1.0))
    min_weight = float(params.get('min_weight', 0.10))
    high_vol_cap = float(params.get('high_vol_cap', 0.35))
    crash_drawdown_threshold = float(params.get('crash_drawdown_threshold', -0.12))
    crash_weight = float(params.get('crash_weight', 0.25))
    rebalance_frequency = str(params.get('rebalance_frequency', 'weekly')).lower()

    out['returns'] = out['close'].pct_change()
    out['realized_vol'] = out['returns'].rolling(vol_window).std() * np.sqrt(252)
    out['rolling_peak'] = out['close'].cummax()
    out['drawdown'] = out['close'] / out['rolling_peak'] - 1.0

    raw_weight = target_vol / out['realized_vol'].replace(0, np.nan)
    out['target_weight'] = raw_weight.clip(lower=min_weight, upper=max_weight)
    out.loc[out['realized_vol'] > high_vol_cap, 'target_weight'] = out.loc[out['realized_vol'] > high_vol_cap, 'target_weight'].clip(upper=0.5)
    out.loc[out['drawdown'] < crash_drawdown_threshold, 'target_weight'] = crash_weight
    out['target_weight'] = out['target_weight'].fillna(0.0)

    if rebalance_frequency == 'weekly':
        week_key = out.index.to_period('W-FRI')
        out['rebalance_signal'] = (week_key != week_key.shift(1)).astype(float)
    elif rebalance_frequency == 'monthly':
        out['rebalance_signal'] = (out.index.month != out.index.month.to_series(index=out.index).shift(1)).astype(float)
    else:
        out['rebalance_signal'] = 1.0

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'realized_vol', 'drawdown', 'target_weight', 'rebalance_signal']].copy()
    return out.dropna(subset=['realized_vol'])


class VolatilityManagedGoldFeed(bt.feeds.PandasData):
    lines = ('realized_vol', 'drawdown', 'target_weight', 'rebalance_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('realized_vol', 6), ('drawdown', 7), ('target_weight', 8), ('rebalance_signal', 9),
    )


class VolatilityManagedGoldStrategy(bt.Strategy):
    params = dict(
        vol_window=20,
        target_vol=0.15,
        max_weight=1.0,
        min_weight=0.10,
        rebalance_frequency="weekly",
        high_vol_cap=0.35,
        crash_drawdown_threshold=-0.12,
        crash_weight=0.25,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.last_target = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if float(self.data.rebalance_signal[0]) <= 0.5:
            return
        target = float(self.data.target_weight[0])
        if self.last_target is not None and abs(self.last_target - target) < 1e-6:
            return
        current_size = self.position.size
        self.last_target = target
        self.pending_order = self.order_target_percent(target=target)
        if self.pending_order is not None:
            if target > 0 and current_size <= 0:
                self.buy_count += 1
            elif target == 0 and current_size > 0:
                self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
