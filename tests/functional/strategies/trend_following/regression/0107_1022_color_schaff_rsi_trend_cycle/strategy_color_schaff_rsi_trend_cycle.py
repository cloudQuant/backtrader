from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
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


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def compute_applied_price(frame, mode):
    mode = str(mode).lower()
    if mode in ('open', 'price_open'):
        return frame['open'].astype(float)
    if mode in ('high', 'price_high'):
        return frame['high'].astype(float)
    if mode in ('low', 'price_low'):
        return frame['low'].astype(float)
    if mode in ('median', 'price_median'):
        return (frame['high'].astype(float) + frame['low'].astype(float)) / 2.0
    if mode in ('typical', 'price_typical'):
        return (frame['high'].astype(float) + frame['low'].astype(float) + frame['close'].astype(float)) / 3.0
    if mode in ('weighted', 'price_weighted'):
        return (frame['high'].astype(float) + frame['low'].astype(float) + 2.0 * frame['close'].astype(float)) / 4.0
    return frame['close'].astype(float)


def compute_rsi(price, period):
    period = int(period)
    delta = price.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(100.0).where(avg_loss != 0.0, 100.0)


def rolling_stochastic(series, window, scale_min=0.0, scale_max=100.0):
    llv = series.rolling(window, min_periods=1).min()
    hhv = series.rolling(window, min_periods=1).max()
    out = pd.Series(index=series.index, dtype='float64')
    prev = np.nan
    for idx, value in enumerate(series.tolist()):
        low = llv.iloc[idx]
        high = hhv.iloc[idx]
        if pd.isna(value) or pd.isna(low) or pd.isna(high):
            out.iloc[idx] = np.nan
            continue
        if high - low != 0:
            out.iloc[idx] = ((value - low) / (high - low)) * (scale_max - scale_min) + scale_min
        else:
            out.iloc[idx] = prev
        prev = out.iloc[idx]
    return out


def recursive_smooth(series, factor=0.5):
    out = []
    prev = np.nan
    for value in series.tolist():
        if pd.isna(value):
            out.append(np.nan)
            continue
        if pd.isna(prev):
            current = value
        else:
            current = factor * (value - prev) + prev
        out.append(current)
        prev = current
    return pd.Series(out, index=series.index, dtype='float64')


def compute_color_schaff_rsi_trend_cycle(frame, fast_rsi=23, slow_rsi=50, applied_price='close', cycle=10, high_level=60, low_level=-60):
    price = compute_applied_price(frame, applied_price)
    fast = compute_rsi(price, fast_rsi)
    slow = compute_rsi(price, slow_rsi)
    macd = fast - slow

    st = rolling_stochastic(macd, int(cycle), scale_min=0.0, scale_max=100.0)
    st = recursive_smooth(st, factor=0.5)
    stc = rolling_stochastic(st, int(cycle), scale_min=-100.0, scale_max=100.0)
    stc = recursive_smooth(stc, factor=0.5)

    color_code = []
    previous = np.nan
    for value in stc.tolist():
        if pd.isna(value):
            color_code.append(np.nan)
            previous = value
            continue
        slope = 0.0 if pd.isna(previous) else value - previous
        clr = 4
        if value > 0:
            if value > high_level:
                clr = 7 if slope >= 0 else 6
            else:
                clr = 5 if slope >= 0 else 4
        if value < 0:
            if value < low_level:
                clr = 0 if slope < 0 else 1
            else:
                clr = 2 if slope < 0 else 3
        color_code.append(float(clr))
        previous = value

    color_code = pd.Series(color_code, index=frame.index, dtype='float64')
    buy_signal = (color_code.shift(1) > 5.0) & (color_code < 6.0)
    sell_signal = (color_code.shift(1) < 2.0) & (color_code > 1.0)

    out = frame.copy()
    out['stc'] = stc
    out['color_code'] = color_code
    out['buy_signal'] = buy_signal.astype(float)
    out['sell_signal'] = sell_signal.astype(float)
    return out.dropna(subset=['stc', 'color_code'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class ColorSchaffRSITrendCycleFeed(bt.feeds.PandasData):
    lines = ('stc', 'color_code', 'buy_signal', 'sell_signal')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('stc', 6),
        ('color_code', 7),
        ('buy_signal', 8),
        ('sell_signal', 9),
    )


class ColorSchaffRSITrendCycleStrategy(bt.Strategy):
    params = dict(
        mm=0.1,
        mm_mode='LOT',
        stop_loss=1000,
        take_profit=2000,
        deviation=10,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        fast_rsi=23,
        slow_rsi=50,
        applied_price='close',
        cycle=10,
        high_level=60,
        low_level=-60,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h4 = self.datas[1]
        self.stc = self.h4.stc
        self.color_code = self.h4.color_code
        self.buy_signal = self.h4.buy_signal
        self.sell_signal = self.h4.sell_signal

        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _signal(self, line, idx):
        try:
            value = float(line[-idx])
        except (TypeError, ValueError, IndexError):
            return False
        return not math.isnan(value) and value > 0.5

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        try:
            float(self.color_code[-idx])
        except (TypeError, ValueError, IndexError):
            return False
        return True

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.m15.high[0])
        low = float(self.m15.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.entry_order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.entry_order = self.close()
                return True
        return False

    def _set_risk_prices(self, side):
        price = float(self.m15.close[0])
        unit = self._trade_unit()
        if side == 'buy':
            self.stop_price = round(price - self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return

        idx = max(int(self.p.signal_bar), 1)
        signal_dt = bt.num2date(self.h4.datetime[-idx])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        buy_open = self.p.buy_pos_open and self._signal(self.buy_signal, idx)
        sell_open = self.p.sell_pos_open and self._signal(self.sell_signal, idx)
        buy_close = self.p.buy_pos_close and sell_open
        sell_close = self.p.sell_pos_close and buy_open

        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1

        self.log('schaff_rsi stc={0:.6f} color={1:.0f} buy_open={2} sell_open={3}'.format(float(self.stc[-idx]), float(self.color_code[-idx]), buy_open, sell_open))

        if buy_close and self.position and self.position.size > 0:
            self.entry_order = self.close()
            return
        if sell_close and self.position and self.position.size < 0:
            self.entry_order = self.close()
            return

        if buy_open and (not self.position or self.position.size <= 0):
            if self.position and self.position.size < 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('buy')
            self.entry_order = self.buy(size=self.p.size)
            return

        if sell_open and (not self.position or self.position.size >= 0):
            if self.position and self.position.size > 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('sell')
            self.entry_order = self.sell(size=self.p.size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
