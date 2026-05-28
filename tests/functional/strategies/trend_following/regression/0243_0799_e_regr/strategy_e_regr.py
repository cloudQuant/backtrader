from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import io
import warnings

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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class ERegrStrategy(bt.Strategy):
    params = dict(
        trade_time='3:00-21:20',
        lots=0.1,
        stop_loss=0,
        take_profit=0,
        protection=1500,
        regr_degree=3,
        regr_kstd=2.0,
        regr_bars=250,
        regr_shift=0,
        trailing_on=False,
        trailing_start=30,
        trailing_size=30,
        repeat_n=3,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.data_h1 = self.datas[0]
        self.data_d1 = self.datas[1] if len(self.datas) > 1 else None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.position_side = None
        self.entry_price = None
        self.entry_dt = None
        self.fixed_stop_price = None
        self.fixed_target_price = None
        self.trailing_stop_price = None
        self._trade_start, self._trade_end = self._parse_trade_window(self.p.trade_time)

    def log(self, text):
        dt = bt.num2date(self.data_h1.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _parse_clock(self, value):
        parts = value.strip().split(':')
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return datetime.time(hour=hour, minute=minute)

    def _parse_trade_window(self, value):
        value = value.strip()
        if value in {'0:00-24:00', '00:00-24:00'}:
            return None, None
        items = [item.strip() for item in value.split('-')]
        if len(items) != 2:
            raise ValueError(f'Invalid trade_time: {value}')
        return self._parse_clock(items[0]), self._parse_clock(items[1])

    def _is_trade_time(self, dt):
        if self._trade_start is None or self._trade_end is None:
            return True
        now = dt.time().replace(second=0, microsecond=0)
        if self._trade_start <= self._trade_end:
            return self._trade_start <= now < self._trade_end
        return now >= self._trade_start or now < self._trade_end

    def _previous_day_range_too_large(self):
        if self.data_d1 is None or len(self.data_d1) < 2:
            return False
        prev_range = float(self.data_d1.high[-1] - self.data_d1.low[-1])
        return prev_range > self.p.protection * self.p.point

    def _compute_channel(self):
        window = self.p.regr_bars + 1
        if len(self.data_h1) < window:
            return None
        closes = np.array([float(self.data_h1.close[-idx]) for idx in range(window)], dtype=float)
        x = np.arange(window, dtype=float)
        degree = max(1, min(int(self.p.regr_degree), window - 1))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            coeffs = np.polyfit(x, closes, degree)
        fitted = np.polyval(coeffs, x)
        std = float(np.sqrt(np.mean(np.square(closes - fitted))) * self.p.regr_kstd)
        mid = round(float(fitted[0]), self.p.price_digits)
        upper = round(mid + std, self.p.price_digits)
        lower = round(mid - std, self.p.price_digits)
        return mid, upper, lower

    def _entry_size(self):
        return round(self.p.lots * self.p.repeat_n, 2)

    def _reset_position_state(self):
        self.position_side = None
        self.entry_price = None
        self.entry_dt = None
        self.fixed_stop_price = None
        self.fixed_target_price = None
        self.trailing_stop_price = None

    def _update_trailing_stop(self, close_price):
        if not self.position or not self.p.trailing_on or self.entry_price is None:
            return
        if self.position.size > 0:
            if close_price - self.entry_price > self.p.trailing_start * self.p.point:
                candidate = round(close_price - self.p.trailing_size * self.p.point, self.p.price_digits)
                if self.trailing_stop_price is None or candidate > self.trailing_stop_price:
                    self.trailing_stop_price = candidate
        else:
            if self.entry_price - close_price > self.p.trailing_start * self.p.point:
                candidate = round(close_price + self.p.trailing_size * self.p.point, self.p.price_digits)
                if self.trailing_stop_price is None or candidate < self.trailing_stop_price:
                    self.trailing_stop_price = candidate

    def _active_stop_price(self):
        if self.position.size > 0:
            candidates = [price for price in (self.fixed_stop_price, self.trailing_stop_price) if price is not None]
            return max(candidates) if candidates else None
        candidates = [price for price in (self.fixed_stop_price, self.trailing_stop_price) if price is not None]
        return min(candidates) if candidates else None

    def _target_price(self, mid_price):
        if self.position.size > 0:
            candidates = [mid_price]
            if self.fixed_target_price is not None:
                candidates.append(self.fixed_target_price)
            return min(candidates)
        candidates = [mid_price]
        if self.fixed_target_price is not None:
            candidates.append(self.fixed_target_price)
        return max(candidates)

    def _close_position(self, reason):
        if self.entry_order is not None:
            return
        self.log(reason)
        self.entry_order = self.close()

    def next(self):
        self.bar_num += 1
        channel = self._compute_channel()
        if channel is None:
            return

        dt = bt.num2date(self.data_h1.datetime[0])
        current_close = round(float(self.data_h1.close[0]), self.p.price_digits)
        current_high = round(float(self.data_h1.high[0]), self.p.price_digits)
        current_low = round(float(self.data_h1.low[0]), self.p.price_digits)
        mid_price, upper_price, lower_price = channel

        if self.position:
            if self._previous_day_range_too_large():
                self._close_position('close by previous D1 protection range')
                return

            self._update_trailing_stop(current_close)
            active_stop = self._active_stop_price()
            active_target = self._target_price(mid_price)

            if self.position.size > 0:
                if active_stop is not None and current_low <= active_stop:
                    self._close_position(f'close long by stop={active_stop:.2f}')
                    return
                if active_target is not None and current_high >= active_target:
                    self._close_position(f'close long by target={active_target:.2f}')
                    return
                if current_close >= mid_price:
                    self._close_position(f'close long by midline={mid_price:.2f}')
                    return
            else:
                if active_stop is not None and current_high >= active_stop:
                    self._close_position(f'close short by stop={active_stop:.2f}')
                    return
                if active_target is not None and current_low <= active_target:
                    self._close_position(f'close short by target={active_target:.2f}')
                    return
                if current_close <= mid_price:
                    self._close_position(f'close short by midline={mid_price:.2f}')
                    return
            return

        if self.entry_order is not None:
            return
        if not self._is_trade_time(dt):
            return
        if self._previous_day_range_too_large():
            return

        size = self._entry_size()
        if current_low <= lower_price:
            self.log(f'buy size={size:.2f} lower={lower_price:.2f} mid={mid_price:.2f}')
            self.entry_order = self.buy(size=size)
            return
        if current_high >= upper_price:
            self.log(f'sell size={size:.2f} upper={upper_price:.2f} mid={mid_price:.2f}')
            self.entry_order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        is_entry_ref = self.entry_order is not None and order.ref == self.entry_order.ref

        if order.status == bt.Order.Completed:
            if order.isbuy() and not self.position:
                pass
            if is_entry_ref and self.position:
                self.entry_price = round(float(order.executed.price), self.p.price_digits)
                self.entry_dt = bt.num2date(order.executed.dt)
                self.position_side = 'long' if order.executed.size > 0 else 'short'
                if order.executed.size > 0:
                    self.buy_count += self.p.repeat_n
                    if self.p.stop_loss > 0:
                        self.fixed_stop_price = round(self.entry_price - self.p.stop_loss * self.p.point, self.p.price_digits)
                    if self.p.take_profit > 0:
                        self.fixed_target_price = round(self.entry_price + self.p.take_profit * self.p.point, self.p.price_digits)
                else:
                    self.sell_count += self.p.repeat_n
                    if self.p.stop_loss > 0:
                        self.fixed_stop_price = round(self.entry_price + self.p.stop_loss * self.p.point, self.p.price_digits)
                    if self.p.take_profit > 0:
                        self.fixed_target_price = round(self.entry_price - self.p.take_profit * self.p.point, self.p.price_digits)
                self.log(f'entry filled price={self.entry_price:.2f} size={order.executed.size:.2f}')
            elif is_entry_ref and not self.position:
                self.log(f'position closed price={order.executed.price:.2f} size={order.executed.size:.2f}')
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if is_entry_ref:
                self.log(f'order failed status={order.getstatusname()}')

        if is_entry_ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm < 0:
            self.loss_count += 1
        else:
            self.win_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
        self._reset_position_state()
