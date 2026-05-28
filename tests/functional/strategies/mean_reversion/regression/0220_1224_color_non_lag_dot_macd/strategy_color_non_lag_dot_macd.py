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
import pandas as pd

MODE_BREAKDOWN = 0
MODE_MACD_TWIST = 1
MODE_SIGNAL_TWIST = 2
MODE_MACD_DISPOSITION = 3

MODE_SMA = 0
MODE_EMA = 1
MODE_SMMA = 2
MODE_LWMA = 3



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


class ColorNonLagDotMacdFeed(btfeeds.PandasData):
    lines = ('macd', 'signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('macd', 6), ('signal', 7),
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


def resolve_applied_price(df, price_code):
    open_ = df['open'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    code = int(price_code)
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


def sma(series, period):
    return pd.Series(series, dtype=float).rolling(int(period), min_periods=int(period)).mean()


def ema(series, period):
    return pd.Series(series, dtype=float).ewm(span=int(period), adjust=False, min_periods=int(period)).mean()


def smma(series, period):
    period = int(period)
    values = pd.Series(series, dtype=float)
    out = [math.nan] * len(values)
    if len(values) < period:
        return pd.Series(out, dtype=float)
    first = values.iloc[:period].mean()
    out[period - 1] = first
    prev = first
    for idx in range(period, len(values)):
        prev = ((prev * (period - 1)) + values.iloc[idx]) / period
        out[idx] = prev
    return pd.Series(out, dtype=float)


def lwma(series, period):
    period = int(period)
    weights = list(range(1, period + 1))
    denom = sum(weights)
    values = pd.Series(series, dtype=float)
    out = [math.nan] * len(values)
    for idx in range(period - 1, len(values)):
        window = values.iloc[idx - period + 1:idx + 1].tolist()
        out[idx] = sum(w * v for w, v in zip(weights, window)) / denom
    return pd.Series(out, dtype=float)


def moving_average(series, period, method):
    method = int(method)
    if method == MODE_SMA:
        return sma(series, period)
    if method == MODE_EMA:
        return ema(series, period)
    if method == MODE_SMMA:
        return smma(series, period)
    if method == MODE_LWMA:
        return lwma(series, period)
    return sma(series, period)


def build_nonlagdot_series(price_series, ma_type, length, filter_value, deviation, point):
    length = int(length)
    coeff = 3.0 * math.pi
    phase = length - 1
    cycle = 4.0
    len_value = int(length * cycle + phase)
    dt1 = (2.0 * cycle - 1.0) / (cycle * length - 1.0)
    dt2 = 1.0 / (phase - 1.0) if phase > 1 else 1.0
    kd = 1.0 + float(deviation) / 100.0
    fi = float(filter_value) * float(point)
    min_rates_total = int(length + len_value + 1)

    ma_series = moving_average(price_series, length, ma_type)
    ma_rev = ma_series.iloc[::-1].tolist()
    n = len(ma_rev)
    ma_buffer = [math.nan] * n
    color_buffer = [math.nan] * n
    if n <= min_rates_total:
        return list(reversed(ma_buffer)), list(reversed(color_buffer))

    limit = n - min_rates_total - 1
    trend0 = 0
    trend1 = 0
    for bar in range(limit, -1, -1):
        weight = 0.0
        sum_value = 0.0
        t = 0.0
        for iii in range(len_value):
            idx = bar + iii
            if idx >= n:
                break
            ma_val = ma_rev[idx]
            if not math.isfinite(ma_val):
                continue
            g = 1.0 / (coeff * t + 1.0)
            if t <= 0.5:
                g = 1.0
            beta = math.cos(math.pi * t)
            alpha = g * beta
            sum_value += alpha * ma_val
            weight += alpha
            if t < 1.0:
                t += dt2
            elif t < len_value - 1:
                t += dt1
        if weight > 0:
            ma_buffer[bar] = kd * sum_value / weight

        if bar > 0 and int(filter_value) > 0 and math.isfinite(ma_buffer[bar]) and math.isfinite(ma_buffer[bar - 1]):
            if abs(ma_buffer[bar] - ma_buffer[bar - 1]) < fi:
                ma_buffer[bar] = ma_buffer[bar - 1]

        trend0 = trend1
        if bar + 1 < n and math.isfinite(ma_buffer[bar]) and math.isfinite(ma_buffer[bar + 1]):
            if ma_buffer[bar] - ma_buffer[bar + 1] > fi:
                trend0 = 1
            if ma_buffer[bar + 1] - ma_buffer[bar] > fi:
                trend0 = -1

        color_buffer[bar] = 0.0
        if trend0 > 0:
            color_buffer[bar] = 2.0
        if trend0 < 0:
            color_buffer[bar] = 1.0
        if bar:
            trend1 = trend0

    return list(reversed(ma_buffer)), list(reversed(color_buffer))


def build_colornonlagdotmacd_frame(df, indicator_minutes, price, filter_value, deviation, fast_type, fast_length, slow_type, slow_length, signal_ma, signal_method, point):
    signal_df = build_resampled_frame(df, indicator_minutes)
    price_series = resolve_applied_price(signal_df, price)
    fast_line, _ = build_nonlagdot_series(price_series, fast_type, fast_length, filter_value, deviation, point)
    slow_line, _ = build_nonlagdot_series(price_series, slow_type, slow_length, filter_value, deviation, point)
    macd = pd.Series(fast_line, dtype=float) - pd.Series(slow_line, dtype=float)
    signal = moving_average(macd, int(signal_ma), int(signal_method))
    signal_df = signal_df.copy()
    signal_df['macd'] = macd.to_numpy()
    signal_df['signal'] = signal.to_numpy()
    return signal_df


class ColorNonLagDotMacdStrategy(bt.Strategy):
    params = dict(
        mode=MODE_MACD_DISPOSITION,
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
        price=0,
        filter_value=0,
        deviation=0.0,
        fast_type=0,
        fast_length=12,
        slow_type=0,
        slow_length=26,
        signal_ma=9,
        signal_method=1,
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
        if len(self.signal) < signal_bar + 2:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        macd_recent = self._line_value(self.signal.macd, signal_bar - 1)
        macd_prev = self._line_value(self.signal.macd, signal_bar)
        macd_old = self._line_value(self.signal.macd, signal_bar + 1)
        sig_recent = self._line_value(self.signal.signal, signal_bar - 1)
        sig_prev = self._line_value(self.signal.signal, signal_bar)
        sig_old = self._line_value(self.signal.signal, signal_bar + 1)
        values = [macd_old, macd_prev, macd_recent]
        signal_values = [sig_old, sig_prev, sig_recent]

        if not all(math.isfinite(v) for v in values + signal_values):
            return

        buy_signal = False
        sell_signal = False
        mode = int(self.p.mode)
        if mode == MODE_BREAKDOWN:
            buy_signal = values[2] > 0 and values[1] <= 0
            sell_signal = values[2] < 0 and values[1] >= 0
        elif mode == MODE_MACD_TWIST:
            buy_signal = values[1] < values[2] and values[0] > values[1]
            sell_signal = values[1] > values[2] and values[0] < values[1]
        elif mode == MODE_SIGNAL_TWIST:
            buy_signal = signal_values[1] < signal_values[2] and signal_values[0] > signal_values[1]
            sell_signal = signal_values[1] > signal_values[2] and signal_values[0] < signal_values[1]
        else:
            buy_signal = values[2] > signal_values[2] and values[1] <= signal_values[1]
            sell_signal = values[2] < signal_values[2] and values[1] >= signal_values[1]

        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} macd={values[2]:.4f} signal={signal_values[2]:.4f} mode={mode}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} macd={values[2]:.4f} signal={signal_values[2]:.4f} mode={mode}')
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
