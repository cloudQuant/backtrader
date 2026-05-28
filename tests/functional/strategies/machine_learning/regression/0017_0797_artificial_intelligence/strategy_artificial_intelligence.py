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


class AccelerationDecelerationOscillator(bt.Indicator):
    lines = ('ac',)
    params = dict(fast=5, slow=34, signal=5)

    def __init__(self):
        median = (self.data.high + self.data.low) / 2.0
        ao = bt.indicators.SimpleMovingAverage(median, period=self.p.fast) - bt.indicators.SimpleMovingAverage(median, period=self.p.slow)
        self.lines.ac = ao - bt.indicators.SimpleMovingAverage(ao, period=self.p.signal)


class ArtificialIntelligenceStrategy(bt.Strategy):
    params = dict(
        x1=76,
        x2=47,
        x3=153,
        x4=135,
        stop_loss=8355,
        lots=1.0,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ac = AccelerationDecelerationOscillator(self.data)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.stop_price = None
        self.entry_price = None
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _perceptron(self):
        w1 = self.p.x1 - 100
        w2 = self.p.x2 - 100
        w3 = self.p.x3 - 100
        w4 = self.p.x4 - 100
        a1 = float(self.ac[0])
        a2 = float(self.ac[-7])
        a3 = float(self.ac[-14])
        a4 = float(self.ac[-21])
        return w1 * a1 + w2 * a2 + w3 * a3 + w4 * a4

    def _set_initial_stop(self, is_long, price):
        if self.p.stop_loss <= 0:
            return None
        if is_long:
            return round(price - self.p.stop_loss * self.p.point, self.p.price_digits)
        return round(price + self.p.stop_loss * self.p.point, self.p.price_digits)

    def _update_management(self, close_price, perceptron_value):
        if not self.position or self.entry_price is None or self.stop_price is None:
            return False
        spread = 0.0
        threshold = self.p.stop_loss * 2 * self.p.point + spread * self.p.point
        if self.position.size > 0:
            if close_price > self.stop_price + threshold:
                if perceptron_value < 0:
                    self.log(f'reverse to short perceptron={perceptron_value:.4f}')
                    self.close()
                    self.sell(size=self.p.lots)
                    return True
                new_stop = round(close_price - self.p.stop_loss * self.p.point, self.p.price_digits)
                if new_stop > self.stop_price:
                    self.stop_price = new_stop
        else:
            if close_price < self.stop_price - threshold:
                if perceptron_value > 0:
                    self.log(f'reverse to long perceptron={perceptron_value:.4f}')
                    self.close()
                    self.buy(size=self.p.lots)
                    return True
                new_stop = round(close_price + self.p.stop_loss * self.p.point, self.p.price_digits)
                if new_stop < self.stop_price:
                    self.stop_price = new_stop
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < 60:
            return
        if self.entry_order is not None:
            return

        close_price = round(float(self.data.close[0]), self.p.price_digits)
        high_price = round(float(self.data.high[0]), self.p.price_digits)
        low_price = round(float(self.data.low[0]), self.p.price_digits)
        perceptron_value = self._perceptron()

        if self.position:
            if self.position.size > 0 and self.stop_price is not None and low_price <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.2f}')
                self.close()
                return
            if self.position.size < 0 and self.stop_price is not None and high_price >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.2f}')
                self.close()
                return
            if self._update_management(close_price, perceptron_value):
                return
            return

        if perceptron_value > 0:
            self.log(f'buy perceptron={perceptron_value:.4f}')
            self.entry_order = self.buy(size=self.p.lots)
            self.stop_price = self._set_initial_stop(True, close_price)
        else:
            self.log(f'sell perceptron={perceptron_value:.4f}')
            self.entry_order = self.sell(size=self.p.lots)
            self.stop_price = self._set_initial_stop(False, close_price)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                self.entry_price = round(float(order.executed.price), self.p.price_digits)
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.log(f'entry filled price={self.entry_price:.2f} size={order.executed.size:.2f}')
            else:
                self.log(f'position closed price={order.executed.price:.2f} size={order.executed.size:.2f}')
                self.entry_price = None
                self.stop_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
