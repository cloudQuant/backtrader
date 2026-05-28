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


def prepare_fifty_fifty_features(price_df, params):
    out = price_df.copy()
    ma_period = int(params.get('ma_period', 200))
    confirmation_days = int(params.get('confirmation_days', 5))
    out['ma'] = out['close'].rolling(ma_period).mean()
    out['above_ma'] = (out['close'] > out['ma']).astype(float)
    out['below_ma'] = (out['close'] < out['ma']).astype(float)
    out['trend_entry_signal'] = (out['above_ma'].rolling(confirmation_days).sum() >= confirmation_days).astype(float)
    out['trend_exit_signal'] = (out['below_ma'].rolling(confirmation_days).sum() >= confirmation_days).astype(float)
    years = pd.Series(out.index.year, index=out.index)
    first_dates = years.groupby(years).transform('idxmin')
    out['is_year_start'] = (pd.Index(out.index) == pd.Index(first_dates)).astype(float)
    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'ma', 'above_ma', 'below_ma', 'trend_entry_signal', 'trend_exit_signal', 'is_year_start',
    ]
    return out[cols].dropna()


class FiftyFiftyFeed(bt.feeds.PandasData):
    lines = ('ma', 'above_ma', 'below_ma', 'trend_entry_signal', 'trend_exit_signal', 'is_year_start',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('ma', 6),
        ('above_ma', 7),
        ('below_ma', 8),
        ('trend_entry_signal', 9),
        ('trend_exit_signal', 10),
        ('is_year_start', 11),
    )


class FiftyFiftyStrategy(bt.Strategy):
    params = dict(
        trend_allocation=0.50,
        buy_hold_allocation=0.50,
        rebalance_threshold=0.03,
        ma_period=200,
        confirmation_days=5,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.rebalance_count = 0
        self.pending_order = None
        self.broker_value_series = []
        self.trend_active = False

    def _current_weight(self):
        portfolio_value = float(self.broker.getvalue())
        if portfolio_value <= 0 or not self.position:
            return 0.0
        return float(self.position.size) * float(self.data.close[0]) / portfolio_value

    def _target_weight(self):
        trend_weight = float(self.p.trend_allocation) if self.trend_active else 0.0
        return float(self.p.buy_hold_allocation) + trend_weight

    def _set_target(self, target):
        current = self._current_weight()
        if target > current:
            self.buy_count += 1
        elif target < current:
            self.sell_count += 1
        self.pending_order = self.order_target_percent(target=target)
        self.rebalance_count += 1

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return

        previous_trend = self.trend_active
        if float(self.data.trend_entry_signal[0]) > 0.5:
            self.trend_active = True
        elif float(self.data.trend_exit_signal[0]) > 0.5:
            self.trend_active = False

        target = self._target_weight()
        current = self._current_weight()
        needs_rebalance = self.bar_num == 1 or float(self.data.is_year_start[0]) > 0.5 or previous_trend != self.trend_active
        if needs_rebalance or abs(target - current) >= float(self.p.rebalance_threshold):
            self._set_target(target)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
