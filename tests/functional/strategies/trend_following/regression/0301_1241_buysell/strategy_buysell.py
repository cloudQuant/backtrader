from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class BuySellFeed(btfeeds.PandasData):
    lines = ('up_trend', 'dn_trend', 'buy_signal', 'sell_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('up_trend', 6), ('dn_trend', 7), ('buy_signal', 8), ('sell_signal', 9),
    )


def build_resampled_frame(df, indicator_minutes):
    rule = f'{int(indicator_minutes)}min'
    signal_df = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    signal_df = signal_df.dropna(subset=['open', 'high', 'low', 'close']).copy()
    signal_df['openinterest'] = signal_df['openinterest'].fillna(0)
    return signal_df


def applied_price(df, code):
    open_ = df['open'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    code = int(code)
    if code == 0:
        return close
    if code == 1:
        return open_
    if code == 2:
        return high
    if code == 3:
        return low
    if code == 4:
        return (high + low) / 2.0
    if code == 5:
        return (high + low + close) / 3.0
    if code == 6:
        return (high + low + 2.0 * close) / 4.0
    return close


def moving_average(series, period, method):
    period = int(period)
    method = int(method)
    if method == 0:
        return series.rolling(period, min_periods=period).mean()
    if method == 1:
        return series.ewm(span=period, adjust=False, min_periods=period).mean()
    if method == 2:
        return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    if method == 3:
        weights = np.arange(1, period + 1, dtype=float)
        return series.rolling(period, min_periods=period).apply(lambda values: float(np.dot(values, weights) / weights.sum()), raw=True)
    return series.rolling(period, min_periods=period).mean()


def atr_wilder(df, period):
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / int(period), adjust=False, min_periods=int(period)).mean()


def build_buysell_frame(df, indicator_minutes, ma_period, ma_method, ma_price, atr_period):
    signal_df = build_resampled_frame(df, indicator_minutes)
    ma_src = applied_price(signal_df, ma_price)
    ma = moving_average(ma_src.astype(float), ma_period, ma_method)
    atr = atr_wilder(signal_df, atr_period)

    up_trend = [math.nan] * len(signal_df)
    dn_trend = [math.nan] * len(signal_df)
    buy_signal = [math.nan] * len(signal_df)
    sell_signal = [math.nan] * len(signal_df)

    ma_values = ma.tolist()
    atr_values = atr.tolist()
    for idx in range(len(signal_df) - 1):
        current_ma = ma_values[idx]
        next_ma = ma_values[idx + 1]
        current_atr = atr_values[idx]
        if not math.isfinite(current_ma) or not math.isfinite(next_ma) or not math.isfinite(current_atr):
            continue

        upper_buffer = current_ma + current_atr if current_ma < next_ma else math.nan
        lower_buffer = current_ma - current_atr if current_ma > next_ma else math.nan
        dn_trend[idx] = upper_buffer
        up_trend[idx] = lower_buffer

    for idx in range(len(signal_df) - 1):
        next_up = up_trend[idx + 1]
        next_dn = dn_trend[idx + 1]
        current_up = up_trend[idx]
        current_dn = dn_trend[idx]
        if math.isfinite(next_up) and math.isfinite(current_dn):
            buy_signal[idx] = current_dn
        if math.isfinite(next_dn) and math.isfinite(current_up):
            sell_signal[idx] = current_up

    signal_df = signal_df.copy()
    signal_df['up_trend'] = up_trend
    signal_df['dn_trend'] = dn_trend
    signal_df['buy_signal'] = buy_signal
    signal_df['sell_signal'] = sell_signal
    return signal_df


class BuySellStrategy(bt.Strategy):
    params = dict(
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        mm=-0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
        ma_period=14,
        ma_method=0,
        ma_price=0,
        atr_period=60,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _line_value(self, line, ago):
        return float(line[-ago]) if ago else float(line[0])

    def _has_value(self, value):
        return math.isfinite(value) and not math.isnan(value) and abs(value) > 1e-12

    def _position_size(self, price):
        if self.p.mm < 0:
            return abs(float(self.p.mm))
        if price <= 0:
            return 0.0
        cash = self.broker.getcash()
        return round((cash * float(self.p.mm)) / price, 4)

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        point_value = float(self.p.point)
        stop_distance = self.p.stop_loss_points * point_value if self.p.stop_loss_points > 0 else None
        take_distance = self.p.take_profit_points * point_value if self.p.take_profit_points > 0 else None
        entry_price = float(self.position.price)

        if self.position.size > 0:
            if stop_distance is not None and close_price <= entry_price - stop_distance:
                self.log(f'close long by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price >= entry_price + take_distance:
                self.log(f'close long by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        elif self.position.size < 0:
            if stop_distance is not None and close_price >= entry_price + stop_distance:
                self.log(f'close short by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price <= entry_price - take_distance:
                self.log(f'close short by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return

        if self._check_exit_levels():
            return

        signal_bar = max(int(self.p.signal_bar), 1)
        if len(self.signal) < signal_bar + 1:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        prev_ago = signal_bar
        recent_up = self._line_value(self.signal.up_trend, recent_ago)
        recent_dn = self._line_value(self.signal.dn_trend, recent_ago)
        prev_up = self._line_value(self.signal.up_trend, prev_ago)
        prev_dn = self._line_value(self.signal.dn_trend, prev_ago)

        buy_signal = self._has_value(recent_up) and self._has_value(prev_dn)
        sell_signal = self._has_value(recent_dn) and self._has_value(prev_up)
        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} recent_up={recent_up:.2f} prev_dn={prev_dn:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} recent_dn={recent_dn:.2f} prev_up={prev_up:.2f}')
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
            if self.position.size >= 0 and self.p.sell_pos_open:
                self.sell(size=size)

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
