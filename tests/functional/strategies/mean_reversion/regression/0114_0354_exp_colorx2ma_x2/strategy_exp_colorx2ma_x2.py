from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
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
    df = df.set_index('datetime').sort_index()
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


class ColorX2MA(bt.Indicator):
    lines = ('value', 'color_idx')
    params = dict(length1=12, length2=5)

    def __init__(self):
        ma1 = bt.indicators.SimpleMovingAverage(self.data.close, period=max(2, self.p.length1))
        ma2 = bt.indicators.SimpleMovingAverage(ma1, period=max(2, self.p.length2))
        self.lines.value = ma2
        self.addminperiod(self.p.length1 + self.p.length2 + 2)

    def next(self):
        current = float(self.lines.value[0])
        prev = float(self.lines.value[-1]) if len(self) > 1 and math.isfinite(float(self.lines.value[-1])) else current
        color = 0.0
        if prev < current:
            color = 1.0
        elif prev > current:
            color = 2.0
        self.lines.color_idx[0] = color


class ExpColorX2MAX2Strategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        risk_percent=0.0,
        point_size=0.01,
        stoploss_pips=1000,
        takeprofit_pips=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        buy_pos_close_fast=False,
        sell_pos_close_fast=False,
        slow_length1=12,
        slow_length2=5,
        slow_signal_bar=1,
        fast_length1=12,
        fast_length2=5,
        fast_signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.fast_feed = self.datas[0]
        self.slow_feed = self.datas[1]
        self.fast_ind = ColorX2MA(self.fast_feed, length1=self.p.fast_length1, length2=self.p.fast_length2)
        self.slow_ind = ColorX2MA(self.slow_feed, length1=self.p.slow_length1, length2=self.p.slow_length2)
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_fast_dt = None
        self.buy_count = 0
        self.sell_count = 0

    def log(self, text):
        dt = bt.num2date(self.fast_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_size(self, size):
        bounded = min(max(size, self.p.lot_min), self.p.lot_max)
        steps = round(bounded / self.p.lot_step)
        return min(max(steps * self.p.lot_step, self.p.lot_min), self.p.lot_max)

    def _position_size(self):
        if self.p.fixed_lot > 0:
            return self._round_size(self.p.fixed_lot)
        stop_distance = self.p.stoploss_pips * self.p.point_size
        if stop_distance <= 0 or self.p.risk_percent <= 0:
            return self._round_size(self.p.lot_min)
        risk_money = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        raw_size = risk_money / (stop_distance * self.p.contract_multiplier)
        return self._round_size(raw_size)

    def _line_value(self, line, signal_bar, previous=False):
        shift = int(signal_bar) + (1 if previous else 0)
        if len(line.array) <= shift:
            return None
        value = float(line[-shift] if shift else line[0])
        if not math.isfinite(value):
            return None
        return value

    def _derived_color(self, current_value, previous_value):
        if current_value is None or previous_value is None:
            return None
        if current_value > previous_value:
            return 1.0
        if current_value < previous_value:
            return 2.0
        return 0.0

    def _trend(self):
        slow_now = self._line_value(self.slow_ind.value, self.p.slow_signal_bar)
        slow_prev = self._line_value(self.slow_ind.value, self.p.slow_signal_bar, previous=True)
        clr = self._derived_color(slow_now, slow_prev)
        if clr == 2.0:
            return -1
        if clr == 1.0:
            return 1
        return 0

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stoploss_pips > 0 else None
            self.take_profit_price = price + take_distance if self.p.takeprofit_pips > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stoploss_pips > 0 else None
            self.take_profit_price = price - take_distance if self.p.takeprofit_pips > 0 else None

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.fast_feed.low[0])
        high = float(self.fast_feed.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                self.log(f'CLOSE long protective stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                self.log(f'CLOSE long take_profit={self.take_profit_price:.5f}')
                return True
            return False
        if self.stop_price is not None and high >= self.stop_price:
            self.order = self.close()
            self.log(f'CLOSE short protective stop={self.stop_price:.5f}')
            return True
        if self.take_profit_price is not None and low <= self.take_profit_price:
            self.order = self.close()
            self.log(f'CLOSE short take_profit={self.take_profit_price:.5f}')
            return True
        return False

    def next(self):
        fast_dt = bt.num2date(self.fast_feed.datetime[0])
        if self.last_fast_dt == fast_dt:
            return
        self.last_fast_dt = fast_dt
        warmup = max(self.p.fast_length1 + self.p.fast_length2 + self.p.fast_signal_bar + 2, self.p.slow_length1 + self.p.slow_length2 + self.p.slow_signal_bar + 2)
        if len(self.fast_feed) < warmup or len(self.slow_feed) < warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        trend = self._trend()
        fast_now = self._line_value(self.fast_ind.value, self.p.fast_signal_bar)
        fast_prev = self._line_value(self.fast_ind.value, self.p.fast_signal_bar, previous=True)
        fast_prev2 = self._line_value(self.fast_ind.value, self.p.fast_signal_bar + 1, previous=True)
        clr_now = self._derived_color(fast_now, fast_prev)
        clr_prev = self._derived_color(fast_prev, fast_prev2)
        if None in (clr_now, clr_prev):
            return
        buy_close = (self.p.buy_pos_close_fast and clr_now == 2.0) or (self.p.buy_pos_close and trend < 0)
        sell_close = (self.p.sell_pos_close_fast and clr_now == 1.0) or (self.p.sell_pos_close and trend > 0)
        if self.position.size > 0 and buy_close:
            self.order = self.close()
            self.log(f'CLOSE long trend={trend} clr_now={clr_now} clr_prev={clr_prev}')
            return
        if self.position.size < 0 and sell_close:
            self.order = self.close()
            self.log(f'CLOSE short trend={trend} clr_now={clr_now} clr_prev={clr_prev}')
            return
        if self.position:
            return
        buy_open = trend > 0 and self.p.buy_pos_open and clr_prev != 1.0 and clr_now == 1.0
        sell_open = trend < 0 and self.p.sell_pos_open and clr_prev != 2.0 and clr_now == 2.0
        size = self._position_size()
        if buy_open:
            self.entry_side = 'long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} trend={trend} clr_now={clr_now} clr_prev={clr_prev}')
        elif sell_open:
            self.entry_side = 'short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} trend={trend} clr_now={clr_now} clr_prev={clr_prev}')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if order == self.order and self.entry_side == 'long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self._set_entry_risk(order.executed.price, 1)
                self.log(f'ENTRY FILLED LONG price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif order == self.order and self.entry_side == 'short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self._set_entry_risk(order.executed.price, -1)
                self.log(f'ENTRY FILLED SHORT price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif not self.position:
                self._clear_risk()
                self.log(f'EXIT FILLED price={order.executed.price:.5f} size={order.executed.size:.2f}')
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            if not self.position:
                self.entry_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self._clear_risk()
            self.entry_side = None
