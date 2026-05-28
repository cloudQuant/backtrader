from __future__ import absolute_import, division, print_function, unicode_literals

import io
import datetime as dt

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


class KettyStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=35,
        takeprofit_pips=75,
        channel_start_hour=7,
        channel_start_min=0,
        channel_end_hour=8,
        channel_end_min=0,
        placing_start_hour=8,
        placing_end_hour=18,
        channel_breakthrough_pips=30,
        order_price_shift_pips=10,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.pending_entry = None
        self.stop_order = None
        self.limit_order = None
        self.active_side = None
        self.last_bar_dt = None
        self.channel_day = None
        self.channel_high = None
        self.channel_low = None
        self.buy_price = None
        self.sell_price = None

    def log(self, text):
        dt0 = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt0.isoformat()}, {text}')

    def prenext(self):
        self.next()

    def _new_bar(self):
        current = bt.num2date(self.data0_feed.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _time_value(self, hour, minute=0):
        return hour * 3600 + minute * 60

    def _current_dt(self):
        return bt.num2date(self.data0_feed.datetime[0])

    def _collect_channel(self, current_dt):
        day = current_dt.date()
        if self.channel_day != day:
            self.channel_day = day
            self.channel_high = None
            self.channel_low = None
        start = self._time_value(self.p.channel_start_hour, self.p.channel_start_min)
        end = self._time_value(self.p.channel_end_hour, self.p.channel_end_min)
        now = self._time_value(current_dt.hour, current_dt.minute)
        if start <= now <= end:
            high = float(self.data0_feed.high[0])
            low = float(self.data0_feed.low[0])
            self.channel_high = high if self.channel_high is None else max(self.channel_high, high)
            self.channel_low = low if self.channel_low is None else min(self.channel_low, low)

    def _cancel_pending_entry(self):
        if self.pending_entry is not None:
            self.cancel(self.pending_entry)
            self.pending_entry = None

    def _delete_expired_pending(self, current_dt):
        if self.pending_entry is None:
            return
        if current_dt.hour > self.p.placing_end_hour or (current_dt.hour == self.p.placing_end_hour and current_dt.minute > 0):
            self.log('DELETE PENDING reason=placing window expired')
            self._cancel_pending_entry()

    def _submit_pending(self, side):
        if self.pending_entry is not None or self.position:
            return
        if self.channel_high is None or self.channel_low is None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        shift = self.p.order_price_shift_pips * self.p.point_size
        if side == 'long':
            price = self.channel_high + shift
            sl = price - stop_distance
            tp = price + take_distance
            self.buy_price = price
            self.pending_entry = self.buy(size=size, exectype=bt.Order.Stop, price=price)
            self.stop_order = ('long', sl)
            self.limit_order = ('long', tp)
            self.log(f'PLACE BUY STOP size={size} price={price:.5f}')
        else:
            price = self.channel_low - shift
            sl = price + stop_distance
            tp = price - take_distance
            self.sell_price = price
            self.pending_entry = self.sell(size=size, exectype=bt.Order.Stop, price=price)
            self.stop_order = ('short', sl)
            self.limit_order = ('short', tp)
            self.log(f'PLACE SELL STOP size={size} price={price:.5f}')

    def _attach_exits_after_fill(self, side, size):
        stop_side, stop_price = self.stop_order
        limit_side, limit_price = self.limit_order
        if side == 'long':
            self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=stop_price)
            self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=limit_price)
        else:
            self.stop_order = self.buy(size=abs(size), exectype=bt.Order.Stop, price=stop_price)
            self.limit_order = self.buy(size=abs(size), exectype=bt.Order.Limit, price=limit_price)

    def next(self):
        if not self._new_bar():
            return
        current_dt = self._current_dt()
        self._collect_channel(current_dt)
        self._delete_expired_pending(current_dt)
        if self.position or self.pending_entry is not None:
            return
        if self.channel_high is None or self.channel_low is None:
            return
        now = self._time_value(current_dt.hour, current_dt.minute)
        start = self._time_value(self.p.placing_start_hour)
        end = self._time_value(self.p.placing_end_hour)
        if not (start <= now <= end):
            return
        breakthrough = self.p.channel_breakthrough_pips * self.p.point_size
        low_prev = float(self.data0_feed.low[-1])
        high_prev = float(self.data0_feed.high[-1])
        if low_prev < self.channel_low - breakthrough:
            self._submit_pending('long')
        elif high_prev > self.channel_high + breakthrough:
            self._submit_pending('short')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.pending_entry:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.pending_entry = None
                self._attach_exits_after_fill(self.active_side, order.executed.size)
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.pending_entry:
                self.pending_entry = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
