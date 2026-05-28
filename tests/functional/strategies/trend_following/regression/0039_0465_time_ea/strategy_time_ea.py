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


class TimeEaStrategy(bt.Strategy):
    params = dict(
        hour_open=1,
        minute_open=0,
        hour_close=0,
        minute_close=0,
        opened_type='buy',
        volume=0.1,
        stop_loss_points=0,
        take_profit_points=0,
        point=0.01,
        compression_minutes=15,
    )

    def __init__(self):
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.stop_price = None
        self.take_profit_price = None
        self.open_time = self.p.hour_open * 60 + self.p.minute_open
        self.close_time = self.p.hour_close * 60 + self.p.minute_close

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None

    def _set_risk(self, price, direction):
        stop_distance = self.p.stop_loss_points * self.p.point
        take_distance = self.p.take_profit_points * self.p.point
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price + take_distance if self.p.take_profit_points > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price - take_distance if self.p.take_profit_points > 0 else None

    def _check_exit_levels(self):
        if not self.position:
            self._clear_risk()
            return False
        if self.position.size > 0:
            if self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and float(self.data.high[0]) >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and float(self.data.low[0]) <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def _minute_of_day(self, dt):
        return dt.hour * 60 + dt.minute

    def _crossed_time(self, prev_minute, curr_minute, target_minute):
        if curr_minute == prev_minute:
            return False
        if curr_minute > prev_minute:
            return prev_minute <= target_minute < curr_minute
        return target_minute >= prev_minute or target_minute < curr_minute

    def next(self):
        self.bar_num += 1
        if len(self.data) < 2:
            return
        if self.order:
            return
        if self._check_exit_levels():
            return

        dt_prev = bt.num2date(self.data.datetime[-1])
        dt_curr = bt.num2date(self.data.datetime[0])
        prev_minute = self._minute_of_day(dt_prev)
        curr_minute = self._minute_of_day(dt_curr)

        if self._crossed_time(prev_minute, curr_minute, self.close_time):
            if self.position:
                self.order = self.close()
                return

        if self._crossed_time(prev_minute, curr_minute, self.open_time):
            desired_long = str(self.p.opened_type).lower() == 'buy'
            if desired_long:
                if self.position.size < 0:
                    self.order = self.close()
                    return
                if self.position.size == 0:
                    self.order = self.buy(size=self.p.volume)
                    return
            else:
                if self.position.size > 0:
                    self.order = self.close()
                    return
                if self.position.size == 0:
                    self.order = self.sell(size=self.p.volume)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and order.executed.size > 0:
                self.buy_count += 1
                if self.position.size > 0:
                    self._set_risk(order.executed.price, 1)
            elif order.issell() and order.executed.size < 0:
                self.sell_count += 1
                if self.position.size < 0:
                    self._set_risk(order.executed.price, -1)
            elif self.position.size == 0:
                self._clear_risk()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self._clear_risk()
