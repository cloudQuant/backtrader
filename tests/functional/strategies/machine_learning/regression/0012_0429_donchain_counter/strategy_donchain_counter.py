from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
from datetime import timedelta

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


class DonchianChannel(bt.Indicator):
    lines = ('upper', 'lower')
    params = dict(period=20)

    def __init__(self):
        period = max(2, int(self.p.period))
        self.lines.upper = bt.indicators.Highest(self.data.high, period=period)
        self.lines.lower = bt.indicators.Lowest(self.data.low, period=period)
        self.addminperiod(period)


class DonchainCounterStrategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        channel_period=20,
        cooldown_hours=24,
        stop_trigger_points=50,
        point=0.01,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
    )

    def __init__(self):
        self.base_feed = self.datas[0]
        self.signal_feed = self.datas[1]
        self.channel = DonchianChannel(self.signal_feed, period=self.p.channel_period)
        self.order = None
        self.entry_side = None
        self.pending_stop_price = None
        self.stop_price = None
        self.last_base_dt = None
        self.last_entry_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0

    def log(self, text):
        dt = bt.num2date(self.base_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_size(self, size):
        bounded = min(max(size, self.p.lot_min), self.p.lot_max)
        steps = round(bounded / self.p.lot_step)
        return min(max(steps * self.p.lot_step, self.p.lot_min), self.p.lot_max)

    def _line_value(self, line, ago=0):
        if len(line.array) <= ago:
            return None
        value = float(line[-ago] if ago else line[0])
        if not math.isfinite(value):
            return None
        return value

    def _position_size(self):
        return self._round_size(self.p.fixed_lot)

    def _cooldown_ready(self, dt):
        if self.last_entry_dt is None:
            return True
        return (dt - self.last_entry_dt) >= timedelta(hours=float(self.p.cooldown_hours))

    def _update_trailing_stop(self):
        if not self.position:
            return
        close_price = float(self.base_feed.close[0])
        current_upper = self._line_value(self.channel.upper, 0)
        current_lower = self._line_value(self.channel.lower, 0)
        trigger_distance = float(self.p.stop_trigger_points) * float(self.p.point)
        if self.position.size > 0:
            if current_lower is None:
                return
            if close_price > current_lower + trigger_distance:
                if self.stop_price is None or current_lower > self.stop_price:
                    self.stop_price = current_lower
                    self.log(f'UPDATE LONG STOP stop={self.stop_price:.5f}')
            return
        if current_upper is None:
            return
        if close_price < current_upper - trigger_distance:
            if self.stop_price is None or current_upper < self.stop_price:
                self.stop_price = current_upper
                self.log(f'UPDATE SHORT STOP stop={self.stop_price:.5f}')

    def _check_stop_exit(self):
        if not self.position or self.stop_price is None:
            return False
        low = float(self.base_feed.low[0])
        high = float(self.base_feed.high[0])
        if self.position.size > 0 and low <= self.stop_price:
            self.order = self.close()
            self.log(f'CLOSE LONG stop={self.stop_price:.5f}')
            return True
        if self.position.size < 0 and high >= self.stop_price:
            self.order = self.close()
            self.log(f'CLOSE SHORT stop={self.stop_price:.5f}')
            return True
        return False

    def next(self):
        dt = bt.num2date(self.base_feed.datetime[0])
        if self.last_base_dt == dt:
            return
        self.last_base_dt = dt
        self.bar_num += 1
        if self.order is not None:
            return
        if len(self.signal_feed) < self.p.channel_period + 3:
            return
        if self.position:
            self._update_trailing_stop()
            self._check_stop_exit()
            return
        if not self._cooldown_ready(dt):
            return
        upper_1 = self._line_value(self.channel.upper, 1)
        upper_2 = self._line_value(self.channel.upper, 2)
        lower_1 = self._line_value(self.channel.lower, 1)
        lower_2 = self._line_value(self.channel.lower, 2)
        stop_short = self._line_value(self.channel.upper, 0)
        stop_long = self._line_value(self.channel.lower, 0)
        if None in (upper_1, upper_2, lower_1, lower_2, stop_short, stop_long):
            return
        size = self._position_size()
        if upper_1 > upper_2:
            self.entry_side = 'long'
            self.pending_stop_price = stop_long
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} stop={stop_long:.5f} upper_1={upper_1:.5f} upper_2={upper_2:.5f}')
            return
        if lower_1 < lower_2:
            self.entry_side = 'short'
            self.pending_stop_price = stop_short
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} stop={stop_short:.5f} lower_1={lower_1:.5f} lower_2={lower_2:.5f}')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if order == self.order and self.entry_side == 'long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self.last_entry_dt = bt.num2date(order.executed.dt) if order.executed.dt else bt.num2date(self.base_feed.datetime[0])
                self.stop_price = self.pending_stop_price
                self.log(f'ENTRY FILLED LONG price={order.executed.price:.5f} size={order.executed.size:.2f} stop={self.stop_price:.5f}')
            elif order == self.order and self.entry_side == 'short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self.last_entry_dt = bt.num2date(order.executed.dt) if order.executed.dt else bt.num2date(self.base_feed.datetime[0])
                self.stop_price = self.pending_stop_price
                self.log(f'ENTRY FILLED SHORT price={order.executed.price:.5f} size={order.executed.size:.2f} stop={self.stop_price:.5f}')
            elif not self.position:
                self.log(f'EXIT FILLED price={order.executed.price:.5f} size={order.executed.size:.2f}')
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            if not self.position:
                self.entry_side = None
                self.pending_stop_price = None
                self.stop_price = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.entry_side = None
            self.pending_stop_price = None
            self.stop_price = None
