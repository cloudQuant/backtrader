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


def prepare_gold_commodity_trend_features(price_df, params):
    fast_ma = int(params.get('fast_ma', 50))
    slow_ma = int(params.get('slow_ma', 200))
    donchian_window = int(params.get('donchian_window', 20))
    atr_window = int(params.get('atr_window', 14))
    base_position_pct = float(params.get('base_position_pct', 0.25))
    max_position_pct = float(params.get('max_position_pct', 1.0))

    out = price_df.copy()
    out['fast_ma'] = out['close'].rolling(fast_ma).mean()
    out['slow_ma'] = out['close'].rolling(slow_ma).mean()
    out['donchian_high'] = out['high'].shift(1).rolling(donchian_window).max()
    out['donchian_low'] = out['low'].shift(1).rolling(donchian_window).min()
    true_range = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low'] - out['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out['atr'] = true_range.rolling(atr_window).mean()
    trend_ma = np.where(out['fast_ma'] > out['slow_ma'], 1.0, -1.0)
    breakout = np.where(out['close'] > out['donchian_high'], 1.0, np.where(out['close'] < out['donchian_low'], -1.0, 0.0))
    out['direction'] = np.where(breakout == trend_ma, breakout, 0.0)
    trend_strength = (out['fast_ma'] - out['slow_ma']).abs() / out['slow_ma'].replace(0, np.nan)
    out['target_pct'] = (base_position_pct * (1.0 + 10.0 * trend_strength)).clip(lower=0.0, upper=max_position_pct)
    out['entry_signal'] = (out['direction'] != 0).astype(float)
    out['exit_signal'] = ((out['direction'] == 0) | ((out['direction'] > 0) & (out['close'] < out['fast_ma'])) | ((out['direction'] < 0) & (out['close'] > out['fast_ma']))).astype(float)
    cols = ['open', 'high', 'low', 'close', 'volume', 'openinterest', 'fast_ma', 'slow_ma', 'donchian_high', 'donchian_low', 'atr', 'direction', 'target_pct', 'entry_signal', 'exit_signal']
    return out[cols].dropna()


class GoldCommodityTrendFeed(bt.feeds.PandasData):
    lines = ('fast_ma', 'slow_ma', 'donchian_high', 'donchian_low', 'atr', 'direction', 'target_pct', 'entry_signal', 'exit_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('fast_ma', 6), ('slow_ma', 7), ('donchian_high', 8), ('donchian_low', 9), ('atr', 10), ('direction', 11), ('target_pct', 12), ('entry_signal', 13), ('exit_signal', 14),
    )


class GoldCommodityTrendStrategy(bt.Strategy):
    params = dict(
        atr_stop_multiplier=3.0,
        allow_short=True,
        fast_ma=50,
        slow_ma=200,
        donchian_window=20,
        atr_window=14,
        base_position_pct=0.25,
        max_position_pct=1.0,
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
            if float(self.data.exit_signal[0]) > 0.5:
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
        target_pct = float(self.data.target_pct[0]) if self.data.target_pct[0] == self.data.target_pct[0] else 0.0
        self.entry_direction = direction
        self.pending_order = self.order_target_percent(target=target_pct * direction)
        if direction > 0:
            self.buy_count += 1
            self.stop_price = close - float(self.p.atr_stop_multiplier) * atr
        else:
            self.sell_count += 1
            self.stop_price = close + float(self.p.atr_stop_multiplier) * atr

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_direction = 0
            self.stop_price = None
