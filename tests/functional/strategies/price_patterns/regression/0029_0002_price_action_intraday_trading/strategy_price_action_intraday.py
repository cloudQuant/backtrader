from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
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
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class PriceActionIntradayStrategy(bt.Strategy):
    params = dict(
        risk_percent=1.5,
        stop_loss_pips=40,
        take_profit_ratio=2.0,
        max_daily_loss=3.0,
        pin_bar_pip_size=10,
        pin_bar_ratio=2.0,
        engulfing_min_pips=15,
        sr_lookback=20,
        sr_tolerance=10.0,
        fast_ma=20,
        slow_ma=50,
        start_hour=2,
        end_hour=20,
        close_at_end_of_day=True,
        magic_number=123456,
        use_break_even=True,
        break_even_pips=20.0,
        use_trailing_stop=True,
        trailing_stop_pips=30.0,
        trailing_step_pips=10.0,
        point=0.01,
        price_digits=2,
        tick_value=1.0,
        tick_size=0.01,
        volume_step=0.01,
        volume_min=0.01,
        volume_max=100.0,
        margin_required_per_lot=250.0,
        lot=0.1,
    )

    def __init__(self):
        self.fast_ma = bt.ind.EMA(self.data.close, period=self.p.fast_ma)
        self.slow_ma = bt.ind.EMA(self.data.close, period=self.p.slow_ma)
        self.entry_order = None
        self.stop_order = None
        self.tp_order = None
        self.close_order = None
        self.entry_price = None
        self.stop_price = None
        self.tp_price = None
        self.daily_start_balance = self.broker.getcash()
        self.current_day = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_value(self):
        return self.p.point * 10.0 if self.p.price_digits in (3, 5) else self.p.point

    def _round_price(self, value):
        return round(value, self.p.price_digits)

    def _round_volume(self, value):
        step = self.p.volume_step
        value = math.floor(value / step) * step if step > 0 else 0.0
        value = max(self.p.volume_min, min(self.p.volume_max, value))
        return round(value, 8)

    def _update_daily_balance_anchor(self):
        dt = bt.num2date(self.data.datetime[0])
        day = dt.date()
        if self.current_day != day:
            self.current_day = day
        if dt.hour == 0 and dt.minute == 0:
            self.daily_start_balance = self.broker.getcash()

    def _is_trading_time(self):
        dt = bt.num2date(self.data.datetime[0])
        return self.p.start_hour <= dt.hour < self.p.end_hour

    def _daily_loss_limit_reached(self):
        if self.daily_start_balance <= 0:
            return False
        current_balance = self.broker.getcash()
        daily_loss = self.daily_start_balance - current_balance
        loss_percent = (daily_loss / self.daily_start_balance) * 100.0
        return loss_percent >= self.p.max_daily_loss

    def _get_trend(self):
        if self.fast_ma[0] > self.slow_ma[0] and self.fast_ma[-1] > self.slow_ma[-1]:
            return 1
        if self.fast_ma[0] < self.slow_ma[0] and self.fast_ma[-1] < self.slow_ma[-1]:
            return -1
        return 0

    def _is_at_support(self, price):
        tolerance = self.p.sr_tolerance * self._pip_value()
        for i in range(2, self.p.sr_lookback):
            if abs(price - float(self.data.low[-i])) < tolerance:
                return True
        return False

    def _is_at_resistance(self, price):
        tolerance = self.p.sr_tolerance * self._pip_value()
        for i in range(2, self.p.sr_lookback):
            if abs(price - float(self.data.high[-i])) < tolerance:
                return True
        return False

    def _pin_bar_signal(self, trend):
        open_ = float(self.data.open[-1])
        high = float(self.data.high[-1])
        low = float(self.data.low[-1])
        close = float(self.data.close[-1])
        body = abs(close - open_)
        upper = high - max(open_, close)
        lower = min(open_, close) - low
        min_wick = self.p.pin_bar_pip_size * self._pip_value()
        is_pin = (
            (lower > min_wick and lower > body * self.p.pin_bar_ratio and upper < body)
            or (upper > min_wick and upper > body * self.p.pin_bar_ratio and lower < body)
        )
        if not is_pin:
            return 0
        if lower > upper * 2 and (trend >= 0 or self._is_at_support(low)):
            return 1
        if upper > lower * 2 and (trend <= 0 or self._is_at_resistance(high)):
            return -1
        return 0

    def _engulfing_signal(self, trend):
        open1 = float(self.data.open[-1])
        close1 = float(self.data.close[-1])
        open2 = float(self.data.open[-2])
        close2 = float(self.data.close[-2])
        candle_size = abs(close1 - open1)
        if candle_size < self.p.engulfing_min_pips * self._pip_value():
            return 0
        bullish = close2 < open2 and close1 > open1 and open1 <= close2 and close1 > open2
        bearish = close2 > open2 and close1 < open1 and open1 >= close2 and close1 < open2
        if bullish and trend >= 0:
            return 1
        if bearish and trend <= 0:
            return -1
        return 0

    def _inside_bar_signal(self, trend):
        high1 = float(self.data.high[-1])
        low1 = float(self.data.low[-1])
        high2 = float(self.data.high[-2])
        low2 = float(self.data.low[-2])
        if not (high1 < high2 and low1 > low2):
            return 0
        close0 = float(self.data.close[0])
        if close0 > high2 and trend >= 0:
            return 1
        if close0 < low2 and trend <= 0:
            return -1
        return 0

    def _calculate_lot_size(self, sl_distance):
        if self.p.tick_value <= 0 or self.p.tick_size <= 0 or sl_distance <= 0:
            return self.p.volume_min
        balance = self.broker.getcash()
        risk_amount = balance * (self.p.risk_percent / 100.0)
        lot = (risk_amount * self.p.tick_size) / (sl_distance * self.p.tick_value)
        if self.p.margin_required_per_lot > 0:
            free_cash = self.broker.getcash()
            lot = min(lot, free_cash / self.p.margin_required_per_lot)
        return self._round_volume(lot)

    def _submit_exit_orders(self):
        size = abs(self.position.size)
        if size <= 0:
            return
        if self.position.size > 0:
            self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            self.tp_order = self.sell(size=size, exectype=bt.Order.Limit, price=self.tp_price, oco=self.stop_order)
        else:
            self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            self.tp_order = self.buy(size=size, exectype=bt.Order.Limit, price=self.tp_price, oco=self.stop_order)

    def _cancel_exit_orders(self):
        for order in (self.stop_order, self.tp_order):
            if order is not None and order.alive():
                self.cancel(order)
        self.stop_order = None
        self.tp_order = None

    def _sync_trade_state(self):
        if not self.position:
            return
        if self.entry_price is None:
            self.entry_price = float(self.position.price)
        pip = self._pip_value()
        sl_distance = self.p.stop_loss_pips * pip
        tp_distance = sl_distance * self.p.take_profit_ratio
        if self.position.size > 0:
            if self.stop_price is None:
                self.stop_price = self._round_price(self.entry_price - sl_distance)
            if self.tp_price is None:
                self.tp_price = self._round_price(self.entry_price + tp_distance)
        else:
            if self.stop_price is None:
                self.stop_price = self._round_price(self.entry_price + sl_distance)
            if self.tp_price is None:
                self.tp_price = self._round_price(self.entry_price - tp_distance)
        if self.stop_order is None and self.tp_order is None and self.close_order is None:
            self._submit_exit_orders()

    def _replace_stop(self, new_stop):
        size = abs(self.position.size)
        if size <= 0:
            return
        if self.position.size > 0 and new_stop <= self.stop_price:
            return
        if self.position.size < 0 and new_stop >= self.stop_price:
            return
        if self.stop_order is not None and self.stop_order.alive():
            self.cancel(self.stop_order)
        self.stop_price = self._round_price(new_stop)
        if self.position.size > 0:
            self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.tp_order)
        else:
            self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.tp_order)
        self.log(f'update stop -> {self.stop_price:.2f}')

    def _manage_position(self):
        if self.close_order is not None and self.close_order.alive():
            return
        self._sync_trade_state()
        current_price = float(self.data.close[0])
        if self.p.use_break_even:
            be_trigger = self.p.break_even_pips * self._pip_value()
            if self.position.size > 0 and current_price >= self.entry_price + be_trigger and self.stop_price < self.entry_price:
                self._replace_stop(self.entry_price)
            if self.position.size < 0 and current_price <= self.entry_price - be_trigger and self.stop_price > self.entry_price:
                self._replace_stop(self.entry_price)
        if self.p.use_trailing_stop:
            trail_distance = self.p.trailing_stop_pips * self._pip_value()
            trail_step = self.p.trailing_step_pips * self._pip_value()
            if self.position.size > 0:
                new_stop = current_price - trail_distance
                if new_stop > self.stop_price + trail_step:
                    self._replace_stop(new_stop)
            else:
                new_stop = current_price + trail_distance
                if new_stop < self.stop_price - trail_step or math.isclose(self.stop_price, 0.0):
                    self._replace_stop(new_stop)

    def _reset_trade_state(self):
        self.entry_order = None
        self.stop_order = None
        self.tp_order = None
        self.close_order = None
        self.entry_price = None
        self.stop_price = None
        self.tp_price = None

    def next(self):
        self.bar_num += 1
        self._update_daily_balance_anchor()
        required_bars = max(self.p.slow_ma, self.p.sr_lookback) + 5
        if len(self.data) < required_bars:
            return
        if not self._is_trading_time():
            if self.p.close_at_end_of_day and self.position and self.close_order is None:
                self._cancel_exit_orders()
                self.close_order = self.close()
                self.log('close at end of day')
            return
        if self._daily_loss_limit_reached():
            return
        if self.position:
            self._manage_position()
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        trend = self._get_trend()
        signal = self._pin_bar_signal(trend)
        if signal == 0:
            signal = self._engulfing_signal(trend)
        if signal == 0:
            signal = self._inside_bar_signal(trend)
        if signal == 0:
            return
        sl_distance = self.p.stop_loss_pips * self._pip_value()
        size = self._calculate_lot_size(sl_distance)
        if size <= 0:
            return
        if signal > 0:
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'buy signal trend={trend} size={size:.2f}')
        else:
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'sell signal trend={trend} size={size:.2f}')

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order is self.entry_order:
            if order.status == order.Completed:
                self.entry_price = float(order.executed.price)
                pip = self._pip_value()
                sl_distance = self.p.stop_loss_pips * pip
                tp_distance = sl_distance * self.p.take_profit_ratio
                if order.isbuy():
                    self.stop_price = self._round_price(self.entry_price - sl_distance)
                    self.tp_price = self._round_price(self.entry_price + tp_distance)
                    self.log(f'buy filled price={self.entry_price:.2f} sl={self.stop_price:.2f} tp={self.tp_price:.2f}')
                else:
                    self.stop_price = self._round_price(self.entry_price + sl_distance)
                    self.tp_price = self._round_price(self.entry_price - tp_distance)
                    self.log(f'sell filled price={self.entry_price:.2f} sl={self.stop_price:.2f} tp={self.tp_price:.2f}')
                self.entry_order = None
                self._submit_exit_orders()
            else:
                self.entry_order = None
            return
        if order is self.stop_order:
            if order.status == order.Completed:
                self.log(f'stop filled price={order.executed.price:.2f}')
                self.stop_order = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.stop_order = None
            return
        if order is self.tp_order:
            if order.status == order.Completed:
                self.log(f'take-profit filled price={order.executed.price:.2f}')
                self.tp_order = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.tp_order = None
            return
        if order is self.close_order:
            if order.status == order.Completed:
                self.log(f'manual close filled price={order.executed.price:.2f}')
                self.close_order = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
        self._reset_trade_state()
