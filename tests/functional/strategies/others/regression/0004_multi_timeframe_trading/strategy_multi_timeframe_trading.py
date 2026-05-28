from __future__ import absolute_import, division, print_function, unicode_literals

import io

import numpy as np
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


def wma(series, period):
    weights = np.arange(1, period + 1)
    return series.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def hull_ma(series, period):
    half_period = max(1, int(period / 2))
    sqrt_period = max(1, int(np.sqrt(period)))
    wma_half = wma(series, half_period)
    wma_full = wma(series, period)
    raw_hma = 2.0 * wma_half - wma_full
    return wma(raw_hma, sqrt_period)


def _resample_ohlc(df, rule):
    return df.resample(rule).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    }).dropna()


def prepare_multi_timeframe_features(df, params):
    primary_period = int(params.get('primary_period', 30))
    signal_period_short = int(params.get('signal_period_short', 15))
    signal_period_long = int(params.get('signal_period_long', 30))
    exit_consecutive_bars = int(params.get('exit_consecutive_bars', 3))

    h1 = df.copy()
    h4 = _resample_ohlc(h1, '4h')
    daily = _resample_ohlc(h1, '1D')

    daily['hma_primary'] = hull_ma(daily['close'], primary_period)
    daily['trend_up'] = (daily['low'] > daily['hma_primary']).astype(float)

    h4['hma_short'] = hull_ma(h4['close'], signal_period_short)
    h4['hma_long'] = hull_ma(h4['close'], signal_period_long)
    h4['entry_cross'] = ((h4['hma_short'] > h4['hma_long']) & (h4['hma_short'].shift(1) <= h4['hma_long'].shift(1))).astype(float)

    h1['trend_up'] = daily['trend_up'].reindex(h1.index, method='ffill').fillna(0.0)
    h1['entry_cross'] = h4['entry_cross'].reindex(h1.index, method='ffill').fillna(0.0)
    entry_edge = h1['entry_cross'].diff().fillna(h1['entry_cross']).clip(lower=0.0)
    h1['entry_signal'] = ((h1['trend_up'] > 0.5) & (entry_edge > 0.5)).astype(float)

    decreasing = pd.Series(True, index=h1.index)
    for shift in range(exit_consecutive_bars):
        decreasing &= h1['close'].shift(shift) < h1['close'].shift(shift + 1)
    h1['exit_signal'] = decreasing.astype(float).fillna(0.0)

    h1 = h1[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'trend_up', 'entry_cross', 'entry_signal', 'exit_signal']].copy()
    return h1.dropna()


class MultiTimeframeSignalFeed(bt.feeds.PandasData):
    lines = ('trend_up', 'entry_cross', 'entry_signal', 'exit_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('trend_up', 6), ('entry_cross', 7), ('entry_signal', 8), ('exit_signal', 9),
    )


class GoldMultiTimeframeTradingStrategy(bt.Strategy):
    params = dict(
        lot_size=1.0,
        primary_period=30,
        signal_period_short=15,
        signal_period_long=30,
        exit_consecutive_bars=3,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
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
        if self.position:
            if float(self.data.exit_signal[0]) > 0.5:
                self.sell_count += 1
                self.pending_order = self.close()
            return
        if float(self.data.entry_signal[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
