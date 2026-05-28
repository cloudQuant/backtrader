from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
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


class MaShiftPuriaMethodStrategy(bt.Strategy):
    params = dict(
        manual_lot=False,
        lot=0.1,
        stop_loss_pips=45,
        take_profit_pips=75,
        trailing_stop_pips=15,
        trailing_step_pips=5,
        risk_percent=9.0,
        max_positions=1,
        fractal_trailing=False,
        ma_fast=14,
        ma_slow=80,
        shift_min_pips=20,
        macd_fast=11,
        macd_slow=102,
        macd_signal=9,
        point=0.01,
        price_digits=2,
        contract_multiplier=100.0,
        min_lot=0.01,
    )

    def __init__(self):
        self.ema_fast = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_fast)
        self.ema_slow = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_slow)
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal,
        )
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._pending_entry_direction = 0
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        self._long_entries = 0
        self._short_entries = 0

    def _pip_size(self):
        digits_adjust = 10 if self.p.price_digits in (3, 5) else 1
        return self.p.point * digits_adjust

    def _risk_based_size(self, entry_price, stop_price):
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return self.p.lot
        risk_cash = self.broker.getcash() * (self.p.risk_percent / 100.0)
        raw_size = risk_cash / (stop_distance * self.p.contract_multiplier)
        size = max(self.p.min_lot, raw_size)
        return round(size, 2)

    def _entry_size(self, direction):
        if self.p.manual_lot or self.p.stop_loss_pips <= 0:
            return self.p.lot
        pip_size = self._pip_size()
        stop_distance = self.p.stop_loss_pips * pip_size
        entry_price = float(self.data.close[0])
        stop_price = entry_price - stop_distance if direction > 0 else entry_price + stop_distance
        return self._risk_based_size(entry_price, stop_price)

    def _clear_position_state(self):
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        self._pending_entry_direction = 0
        if not self.position:
            self._long_entries = 0
            self._short_entries = 0

    def _set_initial_protection(self):
        if not self.position:
            self._clear_position_state()
            return
        if self._entry_price is not None and self._last_position_size == self.position.size:
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        stop_distance = self.p.stop_loss_pips * pip_size
        take_distance = self.p.take_profit_pips * pip_size
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if self.p.stop_loss_pips > 0 else None
            self._take_profit_price = self._entry_price + take_distance if self.p.take_profit_pips > 0 else None
        else:
            self._stop_price = self._entry_price + stop_distance if self.p.stop_loss_pips > 0 else None
            self._take_profit_price = self._entry_price - take_distance if self.p.take_profit_pips > 0 else None

    def _signal_buy(self):
        pip_size = self._pip_size()
        fast_1 = float(self.ema_fast[-1])
        fast_2 = float(self.ema_fast[-2])
        fast_3 = float(self.ema_fast[-3])
        slow_1 = float(self.ema_slow[-1])
        slow_3 = float(self.ema_slow[-3])
        macd_1 = float(self.macd.macd[-1])
        macd_3 = float(self.macd.macd[-3])
        if not (fast_1 > slow_1 and slow_1 > slow_3 and fast_1 > fast_2 and macd_1 > 0.0 and macd_3 < 0.0):
            return False
        x1 = (fast_1 - fast_2) / pip_size
        x2 = (fast_2 - fast_3) / pip_size
        if x1 <= self.p.shift_min_pips:
            return False
        return x1 >= x2 or x2 <= 0.0

    def _signal_sell(self):
        pip_size = self._pip_size()
        fast_1 = float(self.ema_fast[-1])
        fast_2 = float(self.ema_fast[-2])
        fast_3 = float(self.ema_fast[-3])
        slow_1 = float(self.ema_slow[-1])
        slow_3 = float(self.ema_slow[-3])
        macd_1 = float(self.macd.macd[-1])
        macd_3 = float(self.macd.macd[-3])
        if not (fast_1 < slow_1 and slow_1 < slow_3 and fast_1 < fast_2 and macd_1 < 0.0 and macd_3 > 0.0):
            return False
        x1 = (fast_2 - fast_1) / pip_size
        x2 = (fast_3 - fast_2) / pip_size
        if x1 <= self.p.shift_min_pips:
            return False
        return x1 >= x2 or x2 <= 0.0

    def _upper_fractal_shift3(self):
        if len(self.data) < 6:
            return None
        candidate = float(self.data.high[-3])
        if candidate > float(self.data.high[-4]) and candidate > float(self.data.high[-5]) and candidate > float(self.data.high[-2]) and candidate > float(self.data.high[-1]):
            return candidate
        return None

    def _lower_fractal_shift3(self):
        if len(self.data) < 6:
            return None
        candidate = float(self.data.low[-3])
        if candidate < float(self.data.low[-4]) and candidate < float(self.data.low[-5]) and candidate < float(self.data.low[-2]) and candidate < float(self.data.low[-1]):
            return candidate
        return None

    def _maybe_hit_exit(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.order = self.close()
                return True
        return False

    def _update_trailing(self):
        if not self.position:
            return
        current_price = float(self.data.close[0])
        pip_size = self._pip_size()
        trail_stop = self.p.trailing_stop_pips * pip_size
        trail_step = self.p.trailing_step_pips * pip_size
        if self.position.size > 0:
            if self.p.trailing_stop_pips > 0:
                if current_price - self._entry_price > trail_stop + trail_step:
                    threshold = current_price - (trail_stop + trail_step)
                    candidate = current_price - trail_stop
                    if self._stop_price is None or self._stop_price < threshold:
                        self._stop_price = candidate
            elif self.p.fractal_trailing:
                profit_pips = (current_price - self._entry_price) / pip_size
                if profit_pips >= 0.95 * self.p.take_profit_pips:
                    fx = self._lower_fractal_shift3()
                    if fx is not None and (self._stop_price is None or fx > self._stop_price):
                        self._stop_price = fx
        else:
            if self.p.trailing_stop_pips > 0:
                if self._entry_price - current_price > trail_stop + trail_step:
                    threshold = current_price + (trail_stop + trail_step)
                    candidate = current_price + trail_stop
                    if self._stop_price is None or self._stop_price > threshold or self._stop_price == 0:
                        self._stop_price = candidate
            elif self.p.fractal_trailing:
                profit_pips = (self._entry_price - current_price) / pip_size
                if profit_pips >= 0.95 * self.p.take_profit_pips:
                    fx = self._upper_fractal_shift3()
                    if fx is not None and (self._stop_price is None or fx < self._stop_price):
                        self._stop_price = fx

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.ma_slow + 5, self.p.macd_slow + self.p.macd_signal + 5)
        if len(self.data) < warmup:
            return
        if self.order:
            return

        self._set_initial_protection()

        if self._maybe_hit_exit():
            return

        if self.position:
            self._update_trailing()

        can_buy = self.position.size >= 0 and self._long_entries < self.p.max_positions
        can_sell = self.position.size <= 0 and self._short_entries < self.p.max_positions

        if can_buy and self._signal_buy():
            self.buy_count += 1
            self._pending_entry_direction = 1
            self.order = self.buy(size=self._entry_size(1))
            return

        if can_sell and self._signal_sell():
            self.sell_count += 1
            self._pending_entry_direction = -1
            self.order = self.sell(size=self._entry_size(-1))
            return

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if self._pending_entry_direction == 1 and self.position.size > 0:
                self._long_entries += 1
            elif self._pending_entry_direction == -1 and self.position.size < 0:
                self._short_entries += 1
            self._pending_entry_direction = 0
            if self.position:
                self._set_initial_protection()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None
        if not self.position:
            self._clear_position_state()

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self._clear_position_state()
