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


def prepare_trinity_features(df, params):
    out = df.copy()
    trend_ma_window = int(params.get('trend_ma_window', 200))
    tactical_ma_window = int(params.get('tactical_ma_window', 50))
    tactical_momentum_window = int(params.get('tactical_momentum_window', 20))
    core_weight = float(params.get('core_weight', 0.33))
    trend_weight = float(params.get('trend_weight', 0.33))
    tactical_weight = float(params.get('tactical_weight', 0.34))
    rebalance_frequency = str(params.get('rebalance_frequency', 'monthly')).lower()

    out['trend_ma'] = out['close'].rolling(trend_ma_window).mean()
    out['tactical_ma'] = out['close'].rolling(tactical_ma_window).mean()
    out['tactical_momentum'] = out['close'].pct_change(tactical_momentum_window)

    out['core_alloc'] = core_weight
    out['trend_alloc'] = trend_weight * (out['close'] > out['trend_ma']).astype(float)
    out['tactical_alloc'] = tactical_weight * ((out['close'] > out['tactical_ma']) & (out['tactical_momentum'] > 0)).astype(float)
    out['target_weight'] = out['core_alloc'] + out['trend_alloc'] + out['tactical_alloc']

    if rebalance_frequency == 'monthly':
        period_key = out.index.to_period('M')
        out['rebalance_signal'] = (period_key != period_key.shift(1)).astype(float)
    elif rebalance_frequency == 'weekly':
        period_key = out.index.to_period('W-FRI')
        out['rebalance_signal'] = (period_key != period_key.shift(1)).astype(float)
    else:
        out['rebalance_signal'] = 1.0

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'trend_ma', 'tactical_ma', 'tactical_momentum', 'core_alloc', 'trend_alloc', 'tactical_alloc', 'target_weight', 'rebalance_signal']].copy()
    return out.dropna(subset=['trend_ma', 'tactical_ma', 'tactical_momentum'])


class TrinityGoldFeed(bt.feeds.PandasData):
    lines = ('trend_ma', 'tactical_ma', 'tactical_momentum', 'core_alloc', 'trend_alloc', 'tactical_alloc', 'target_weight', 'rebalance_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('trend_ma', 6), ('tactical_ma', 7), ('tactical_momentum', 8), ('core_alloc', 9), ('trend_alloc', 10), ('tactical_alloc', 11), ('target_weight', 12), ('rebalance_signal', 13),
    )


class TrinityPortfolioGoldStrategy(bt.Strategy):
    params = dict(
        core_weight=0.33,
        trend_weight=0.33,
        tactical_weight=0.34,
        trend_ma_window=200,
        tactical_ma_window=50,
        tactical_momentum_window=20,
        rebalance_frequency="monthly",
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
