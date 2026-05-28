from __future__ import absolute_import, division, print_function, unicode_literals

import io
import random

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


class RndTradeStrategy(bt.Strategy):
    params = dict(
        interval_minutes=60,
        compression_minutes=15,
        volume=0.1,
        random_seed=42,
    )

    def __init__(self):
        self.orders = []
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.elapsed_minutes = 0.0
        self.rng = random.Random(self.p.random_seed)

    def next(self):
        self.bar_num += 1
        if len(self.data) < 2:
            return
        if self.orders:
            return

        dt_prev = bt.num2date(self.data.datetime[-1])
        dt_curr = bt.num2date(self.data.datetime[0])
        delta_minutes = max((dt_curr - dt_prev).total_seconds() / 60.0, 0.0)
        self.elapsed_minutes += delta_minutes
        if self.elapsed_minutes + 1e-9 < self.p.interval_minutes:
            return
        self.elapsed_minutes = 0.0

        new_orders = []
        if self.position:
            close_order = self.close()
            if close_order is not None:
                new_orders.append(close_order)

        if self.rng.random() < 0.5:
            order = self.buy(size=self.p.volume)
        else:
            order = self.sell(size=self.p.volume)
        if order is not None:
            new_orders.append(order)
        self.orders.extend(new_orders)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order in self.orders:
            self.orders.remove(order)
        if order.status == order.Completed:
            if order.isbuy() and order.executed.size > 0:
                self.buy_count += 1
            elif order.issell() and order.executed.size < 0:
                self.sell_count += 1

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
