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
    df = df.rename(columns={'<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close', '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume'})
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def _omega(returns, threshold):
    gains = (returns[returns > threshold] - threshold).sum()
    losses = (threshold - returns[returns <= threshold]).sum()
    if losses <= 0:
        return float('inf') if gains > 0 else 1.0
    return gains / losses


def prepare_omega_features(df, params):
    threshold = float(params.get('threshold', 0.0))
    window = int(params.get('window', 252))
    upper = float(params.get('upper_threshold', 1.2))
    lower = float(params.get('lower_threshold', 0.8))
    out = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    out['returns'] = out['close'].pct_change()
    omega_values = []
    for i in range(len(out)):
        if i < window:
            omega_values.append(float('nan'))
            continue
        omega_values.append(_omega(out['returns'].iloc[i - window:i].dropna(), threshold))
    out['omega'] = omega_values
    out['signal'] = 0.0
    out.loc[out['omega'] > upper, 'signal'] = 1.0
    out.loc[out['omega'] < lower, 'signal'] = 0.0
    return out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'returns', 'omega', 'signal']].dropna().copy()


class OmegaRatioFeed(bt.feeds.PandasData):
    lines = ('returns', 'omega', 'signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('returns', 6), ('omega', 7), ('signal', 8),
    )


class OmegaRatioStrategy(bt.Strategy):
    params = dict(
        rebalance_interval_days=5,
        position_size=0.90,
        threshold=0.0,
        window=252,
        upper_threshold=1.2,
        lower_threshold=0.8,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.broker_value_series = []

    def _current_weight(self):
        value = float(self.broker.getvalue())
        if value <= 0 or not self.position:
            return 0.0
        return float(self.position.size) * float(self.data.close[0]) / value

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        target = float(self.p.position_size) if float(self.data.signal[0]) > 0.5 else 0.0
        current = self._current_weight()
        if abs(target - current) < 0.01:
            return
        if target > current:
            self.buy_count += 1
        else:
            self.sell_count += 1
        self.pending_order = self.order_target_percent(target=target)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
