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


def compute_trix(close, period):
    ema1 = close.ewm(span=int(period), adjust=False, min_periods=int(period)).mean()
    ema2 = ema1.ewm(span=int(period), adjust=False, min_periods=int(period)).mean()
    ema3 = ema2.ewm(span=int(period), adjust=False, min_periods=int(period)).mean()
    return ema3.pct_change() * 100.0


def compute_color_zerolag_trix(frame, smoothing=15, factor1=0.05, trix_period1=8, factor2=0.10, trix_period2=21, factor3=0.16, trix_period3=34, factor4=0.26, trix_period4=55, factor5=0.43, trix_period5=89):
    close = frame['close'].astype(float)
    trix1 = compute_trix(close, trix_period1)
    trix2 = compute_trix(close, trix_period2)
    trix3 = compute_trix(close, trix_period3)
    trix4 = compute_trix(close, trix_period4)
    trix5 = compute_trix(close, trix_period5)

    fast = factor1 * trix1 + factor2 * trix2 + factor2 * trix3 + factor4 * trix4 + factor5 * trix5
    smooth_const = (float(smoothing) - 1.0) / float(smoothing)
    slow_values = []
    prev_slow = np.nan
    for value in fast.tolist():
        if pd.isna(value):
            slow_values.append(np.nan)
            continue
        if pd.isna(prev_slow):
            prev_slow = value / float(smoothing)
        else:
            prev_slow = value / float(smoothing) + prev_slow * smooth_const
        slow_values.append(prev_slow)
    slow = pd.Series(slow_values, index=frame.index, dtype='float64')

    buy_signal = (fast.shift(1) > slow.shift(1)) & (fast < slow)
    sell_signal = (fast.shift(1) < slow.shift(1)) & (fast > slow)

    out = frame.copy()
    out['fast'] = fast
    out['slow'] = slow
    out['buy_signal'] = buy_signal.astype(float)
    out['sell_signal'] = sell_signal.astype(float)
    return out.dropna(subset=['fast', 'slow'])


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


class ColorZerolagTriXFeed(bt.feeds.PandasData):
    lines = ('fast', 'slow', 'buy_signal', 'sell_signal')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('fast', 6),
        ('slow', 7),
        ('buy_signal', 8),
        ('sell_signal', 9),
    )


class ColorZerolagTriXStrategy(bt.Strategy):
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
        smoothing=15,
        factor1=0.05,
        trix_period1=8,
        factor2=0.1,
        trix_period2=21,
        factor3=0.16,
        trix_period3=34,
        factor4=0.26,
        trix_period4=55,
        factor5=0.43,
        trix_period5=89,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h4 = self.datas[1]
        self.fast = self.h4.fast
        self.slow = self.h4.slow
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
            float(self.fast[-idx])
            float(self.slow[-idx])
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

        self.log('zerolagtrix fast={0:.6f} slow={1:.6f} buy_open={2} sell_open={3}'.format(float(self.fast[-idx]), float(self.slow[-idx]), buy_open, sell_open))

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
