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


class PercentageCrossoverChannel(bt.Indicator):
    lines = ('upper', 'middle', 'lower')
    params = dict(percent=50.0)

    def __init__(self):
        self.addminperiod(2)
        percent = max(self.p.percent, 0.001) / 100.0
        self.plus_value = 1 + percent / 100.0
        self.minus_value = 1 - percent / 100.0

    def next(self):
        price = float(self.data.close[0])
        if len(self.data) == 1 or self.lines.middle[-1] != self.lines.middle[-1]:
            middle = price
        else:
            prev_middle = float(self.lines.middle[-1])
            if price * self.minus_value > prev_middle:
                middle = price * self.minus_value
            elif price * self.plus_value < prev_middle:
                middle = price * self.plus_value
            else:
                middle = prev_middle
        self.lines.middle[0] = middle
        self.lines.upper[0] = middle * self.plus_value
        self.lines.lower[0] = middle * self.minus_value


class PercentageCrossoverChannelStrategy(bt.Strategy):
    params = dict(
        percent=50.0,
        cross_middle=False,
        reverse_trade=False,
        volume=0.1,
        stop_loss_points=0,
        take_profit_points=0,
        point=0.01,
    )

    def __init__(self):
        self.channel = PercentageCrossoverChannel(self.data, percent=self.p.percent)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.stop_price = None
        self.take_profit_price = None

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

    def next(self):
        self.bar_num += 1
        if len(self.data) < 4:
            return
        if self.order:
            return
        if self._check_exit_levels():
            return

        line_up1 = float(self.channel.upper[-1])
        line_up2 = float(self.channel.upper[-2])
        line_md1 = float(self.channel.middle[-1])
        line_md2 = float(self.channel.middle[-2])
        line_dn1 = float(self.channel.lower[-1])
        line_dn2 = float(self.channel.lower[-2])

        open_long = False
        open_short = False
        if self.p.cross_middle:
            if float(self.data.close[-2]) > line_md2 and float(self.data.close[-1]) < line_md1:
                open_long = not self.p.reverse_trade
                open_short = self.p.reverse_trade
            if float(self.data.close[-2]) < line_md2 and float(self.data.close[-1]) > line_md1:
                open_short = not self.p.reverse_trade
                open_long = self.p.reverse_trade
        else:
            if float(self.data.low[-2]) > line_dn2 and float(self.data.low[-1]) <= line_dn1:
                open_long = not self.p.reverse_trade
                open_short = self.p.reverse_trade
            if float(self.data.high[-2]) < line_up2 and float(self.data.high[-1]) >= line_up1:
                open_short = not self.p.reverse_trade
                open_long = self.p.reverse_trade

        if open_long:
            if self.position.size < 0:
                self.order = self.close()
                return
            if self.position.size == 0:
                self.order = self.buy(size=self.p.volume)
                return
        if open_short:
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
