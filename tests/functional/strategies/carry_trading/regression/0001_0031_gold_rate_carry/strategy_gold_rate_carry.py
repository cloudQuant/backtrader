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


def rolling_zscore(series, window):
    mean = series.rolling(window).mean()
    std = series.rolling(window).std().replace(0, np.nan)
    return (series - mean) / std


def prepare_gold_rate_carry_features(gold_df, rate_proxy_df, params):
    relationship_window = int(params.get('relationship_window', 126))
    rate_window = int(params.get('rate_window', 126))
    entry_z = float(params.get('entry_z', 1.0))
    spread_entry_z = float(params.get('spread_entry_z', 0.5))
    atr_window = int(params.get('atr_window', 14))

    gold = gold_df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    rate_proxy = rate_proxy_df[['close']].rename(columns={'close': 'rate_proxy_close'})
    out = gold.join(rate_proxy, how='inner').dropna().copy()

    gold_log = np.log(out['close'])
    rate_log = np.log(out['rate_proxy_close'])
    cov = gold_log.rolling(relationship_window).cov(rate_log)
    var = rate_log.rolling(relationship_window).var().replace(0, np.nan)
    out['beta'] = cov / var
    out['fair_value'] = out['beta'] * rate_log
    out['spread'] = gold_log - out['fair_value']
    out['spread_z'] = rolling_zscore(out['spread'], relationship_window)
    out['rate_z'] = rolling_zscore(rate_log, rate_window)

    true_range = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low'] - out['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out['atr'] = true_range.rolling(atr_window).mean()

    out['direction'] = 0.0
    long_mask = (out['rate_z'] > entry_z) & (out['spread_z'] < -spread_entry_z)
    short_mask = (out['rate_z'] < -entry_z) & (out['spread_z'] > spread_entry_z)
    out.loc[long_mask, 'direction'] = 1.0
    out.loc[short_mask, 'direction'] = -1.0
    out['entry_signal'] = (out['direction'] != 0).astype(float)
    out['exit_signal'] = (out['spread_z'].abs() < float(params.get('exit_z', 0.2))).astype(float)

    cols = ['open', 'high', 'low', 'close', 'volume', 'openinterest', 'rate_proxy_close', 'beta', 'spread', 'spread_z', 'rate_z', 'atr', 'direction', 'entry_signal', 'exit_signal']
    return out[cols].dropna()


class GoldRateCarryFeed(bt.feeds.PandasData):
    lines = ('rate_proxy_close', 'beta', 'spread', 'spread_z', 'rate_z', 'atr', 'direction', 'entry_signal', 'exit_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('rate_proxy_close', 6), ('beta', 7), ('spread', 8), ('spread_z', 9), ('rate_z', 10), ('atr', 11), ('direction', 12), ('entry_signal', 13), ('exit_signal', 14),
    )


class GoldRateCarryStrategy(bt.Strategy):
    params = dict(
        position_pct=0.25,
        atr_stop_multiplier=3.0,
        allow_short=True,
        relationship_window=126,
        rate_window=126,
        entry_z=1.0,
        spread_entry_z=0.5,
        exit_z=0.2,
        atr_window=14,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_direction = 0
        self.stop_price = None
        self.broker_value_series = []

    def _position_size(self):
        broker_value = float(self.broker.getvalue())
        price = float(self.data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        return max(0.01, round(broker_value * float(self.p.position_pct) / price, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        close = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        atr = float(self.data.atr[0]) if self.data.atr[0] == self.data.atr[0] else 0.0
        if self.position:
            if self.entry_direction > 0 and self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.entry_direction < 0 and self.stop_price is not None and high >= self.stop_price:
                self.buy_count += 1
                self.pending_order = self.close()
                return
            if float(self.data.exit_signal[0]) > 0.5 or int(round(float(self.data.direction[0]))) != self.entry_direction:
                if self.entry_direction > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
                self.pending_order = self.close()
                return
            return
        if float(self.data.entry_signal[0]) <= 0.5:
            return
        direction = int(round(float(self.data.direction[0]))) if self.data.direction[0] == self.data.direction[0] else 0
        if direction == 0 or (direction < 0 and not bool(self.p.allow_short)):
            return
        size = self._position_size()
        self.entry_direction = direction
        if direction > 0:
            self.buy_count += 1
            self.pending_order = self.buy(size=size)
            self.stop_price = close - float(self.p.atr_stop_multiplier) * atr
        else:
            self.sell_count += 1
            self.pending_order = self.sell(size=size)
            self.stop_price = close + float(self.p.atr_stop_multiplier) * atr

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_direction = 0
            self.stop_price = None
