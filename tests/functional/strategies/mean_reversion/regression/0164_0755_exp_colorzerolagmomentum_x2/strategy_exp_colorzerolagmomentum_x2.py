from __future__ import absolute_import, division, print_function, unicode_literals

import io

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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'openinterest']]
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
        'tick_volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    out['volume'] = out['tick_volume']
    return out


def price_series(frame, applied_price='PRICE_CLOSE'):
    mapping = str(applied_price).upper()
    if mapping == 'PRICE_OPEN':
        return frame['open']
    if mapping == 'PRICE_HIGH':
        return frame['high']
    if mapping == 'PRICE_LOW':
        return frame['low']
    if mapping == 'PRICE_MEDIAN':
        return (frame['high'] + frame['low']) / 2.0
    if mapping == 'PRICE_TYPICAL':
        return (frame['high'] + frame['low'] + frame['close']) / 3.0
    if mapping == 'PRICE_WEIGHTED':
        return (frame['high'] + frame['low'] + 2.0 * frame['close']) / 4.0
    return frame['close']


def compute_momentum(values, period):
    series = pd.Series(values, dtype=float)
    return (series / series.shift(int(period))) * 100.0


def compute_color_zerolag_momentum(frame, smoothing=15, applied_price='PRICE_CLOSE', factor1=0.05, momentum_period1=8, factor2=0.10, momentum_period2=21, factor3=0.16, momentum_period3=34, factor4=0.26, momentum_period4=55, factor5=0.43, momentum_period5=89):
    out = frame.copy()
    src = price_series(out, applied_price)
    m1 = compute_momentum(src, momentum_period1)
    m2 = compute_momentum(src, momentum_period2)
    m3 = compute_momentum(src, momentum_period3)
    m4 = compute_momentum(src, momentum_period4)
    m5 = compute_momentum(src, momentum_period5)
    fast = factor1 * m1 + factor2 * m2 + factor2 * m3 + factor4 * m4 + factor5 * m5
    slow = fast.ewm(alpha=1.0 / float(smoothing), adjust=False).mean()
    out['main_line'] = fast
    out['signal_line'] = slow
    out = out.dropna(subset=['main_line', 'signal_line'])
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class ColorZerolagFeed(bt.feeds.PandasData):
    lines = ('main_line', 'signal_line')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('main_line', 6), ('signal_line', 7),
    )


class ExpColorZerolagMomentumX2Strategy(bt.Strategy):
    params = dict(
        slow_tf_minutes=360,
        fast_tf_minutes=30,
        signal_bar=1,
        signal_bar_fast=1,
        stop_loss=1000,
        take_profit=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        buy_pos_close_fast=False,
        sell_pos_close_fast=False,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        size=0.1,
        smoothing=15,
        applied_price='PRICE_CLOSE',
        factor1=0.05,
        momentum_period1=8,
        factor2=0.1,
        momentum_period2=21,
        factor3=0.16,
        momentum_period3=34,
        factor4=0.26,
        momentum_period4=55,
        factor5=0.43,
        momentum_period5=89,
        smoothing_fast=15,
        applied_price_fast='PRICE_CLOSE',
        factor1_fast=0.05,
        momentum_period1_fast=8,
        factor2_fast=0.1,
        momentum_period2_fast=21,
        factor3_fast=0.16,
        momentum_period3_fast=34,
        factor4_fast=0.26,
        momentum_period4_fast=55,
        factor5_fast=0.43,
        momentum_period5_fast=89,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.slow = self.datas[1]
        self.fast = self.datas[2]
        self.slow_main = self.slow.main_line
        self.slow_signal = self.slow.signal_line
        self.fast_main = self.fast.main_line
        self.fast_signal = self.fast.signal_line

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.order = None
        self.last_fast_signal_dt = None
        self.stop_price = None
        self.take_profit_price = None

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _set_risk(self, side):
        price = float(self.base.close[0])
        unit = self._unit()
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def _enough_history(self):
        try:
            _ = float(self.slow_main[-max(int(self.p.signal_bar), 1)])
            _ = float(self.slow_signal[-max(int(self.p.signal_bar), 1)])
            _ = float(self.fast_main[-(max(int(self.p.signal_bar_fast), 1) + 1)])
            _ = float(self.fast_signal[-(max(int(self.p.signal_bar_fast), 1) + 1)])
            return True
        except (IndexError, TypeError, ValueError):
            return False

    def _trend_direction(self):
        idx = max(int(self.p.signal_bar), 1)
        slow_main = float(self.slow_main[-idx])
        slow_signal = float(self.slow_signal[-idx])
        if slow_main < slow_signal:
            return -1, slow_main, slow_signal
        if slow_main > slow_signal:
            return 1, slow_main, slow_signal
        return 0, slow_main, slow_signal

    def _fast_signals(self, trend):
        idx = max(int(self.p.signal_bar_fast), 1)
        curr_main = float(self.fast_main[-idx])
        prev_main = float(self.fast_main[-(idx + 1)])
        curr_signal = float(self.fast_signal[-idx])
        prev_signal = float(self.fast_signal[-(idx + 1)])
        buy_open = buy_close = sell_open = sell_close = False
        if self.p.buy_pos_close_fast and prev_main < prev_signal:
            buy_close = True
        if self.p.sell_pos_close_fast and prev_main > prev_signal:
            sell_close = True
        if trend < 0:
            if self.p.buy_pos_close:
                buy_close = True
            if self.p.sell_pos_open and curr_main >= curr_signal and prev_main < prev_signal:
                sell_open = True
        if trend > 0:
            if self.p.sell_pos_close:
                sell_close = True
            if self.p.buy_pos_open and curr_main <= curr_signal and prev_main > prev_signal:
                buy_open = True
        return buy_open, buy_close, sell_open, sell_close, prev_main, prev_signal, curr_main, curr_signal

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self._manage_risk():
            return
        if not self._enough_history():
            return
        idx = max(int(self.p.signal_bar_fast), 1)
        signal_dt = bt.num2date(self.fast.datetime[-idx])
        if self.last_fast_signal_dt == signal_dt:
            return
        self.last_fast_signal_dt = signal_dt
        trend, slow_main, slow_signal = self._trend_direction()
        buy_open, buy_close, sell_open, sell_close, prev_main, prev_signal, curr_main, curr_signal = self._fast_signals(trend)
        if buy_open or sell_open:
            self.signal_count += 1
        self.log(
            f'czm slow=({slow_main:.4f},{slow_signal:.4f}) fast_prev=({prev_main:.4f},{prev_signal:.4f}) '
            f'fast_curr=({curr_main:.4f},{curr_signal:.4f}) buy_open={buy_open} sell_open={sell_open}'
        )
        if buy_close and self.position and self.position.size > 0:
            self.order = self.close()
            return
        if sell_close and self.position and self.position.size < 0:
            self.order = self.close()
            return
        if buy_open and (not self.position or self.position.size <= 0):
            if self.position and self.position.size < 0:
                self.order = self.close()
                return
            self._set_risk('buy')
            self.order = self.buy(size=self.p.size)
            return
        if sell_open and (not self.position or self.position.size >= 0):
            if self.position and self.position.size > 0:
                self.order = self.close()
                return
            self._set_risk('sell')
            self.order = self.sell(size=self.p.size)

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
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
