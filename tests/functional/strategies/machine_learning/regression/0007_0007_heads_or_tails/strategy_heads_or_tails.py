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


class HeadsOrTailsStrategy(bt.Strategy):
    params = dict(
        iLots=0.01,
        iTakeProfit=450,
        iStopLoss=390,
        iMagicNumber=227,
        iSlippage=30,
        point=0.01,
        price_digits=2,
        volume_step=0.01,
        volume_min=0.01,
        volume_max=100.0,
        random_seed=227,
    )

    def __init__(self):
        self.lt = 0.0
        self.entry_order = None
        self.stop_order = None
        self.tp_order = None
        self.rng = random.Random(self.p.random_seed)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._prepare_lot()

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_price(self, value):
        return round(value, self.p.price_digits)

    def _prepare_lot(self):
        step = self.p.volume_step
        if step > 0:
            self.lt = step * max(0, int(self.p.iLots / step) - 1)
        if self.lt < self.p.volume_min:
            self.lt = 0.0
        if self.lt > self.p.volume_max:
            self.lt = self.p.volume_max

    def start(self):
        if self.lt <= 0:
            print('effective lot size is 0.0 after original MT5 volume normalization; strategy will not open trades with current defaults')

    def _cancel_exit_orders(self):
        for order in (self.stop_order, self.tp_order):
            if order is not None and order.alive():
                self.cancel(order)
        self.stop_order = None
        self.tp_order = None

    def _ensure_exit_orders(self):
        if not self.position or self.stop_order is not None or self.tp_order is not None:
            return
        current_price = float(self.data.close[0])
        size = abs(self.position.size)
        if self.position.size > 0:
            stop_price = self._round_price(current_price - self.p.iStopLoss * self.p.point)
            tp_price = self._round_price(current_price + self.p.iTakeProfit * self.p.point)
            self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=stop_price)
            self.tp_order = self.sell(size=size, exectype=bt.Order.Limit, price=tp_price, oco=self.stop_order)
        else:
            stop_price = self._round_price(current_price + self.p.iStopLoss * self.p.point)
            tp_price = self._round_price(current_price - self.p.iTakeProfit * self.p.point)
            self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=stop_price)
            self.tp_order = self.buy(size=size, exectype=bt.Order.Limit, price=tp_price, oco=self.stop_order)
        self.log(f'apply exits sl={stop_price:.2f} tp={tp_price:.2f}')

    def next(self):
        self.bar_num += 1
        if self.lt <= 0:
            return
        if self.position:
            self._ensure_exit_orders()
            return
        if self.entry_order is not None:
            return
        direction = self.rng.randrange(2)
        if direction == 0:
            self.entry_order = self.buy(size=self.lt)
            self.buy_count += 1
            self.log(f'random buy signal size={self.lt:.2f}')
        else:
            self.entry_order = self.sell(size=self.lt)
            self.sell_count += 1
            self.log(f'random sell signal size={self.lt:.2f}')

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order is self.entry_order:
            if order.status == order.Completed:
                side = 'buy' if order.isbuy() else 'sell'
                self.log(f'{side} filled price={order.executed.price:.2f}')
                self.entry_order = None
            else:
                self.entry_order = None
            return
        if order is self.stop_order:
            if order.status == order.Completed:
                self.log(f'stop filled price={order.executed.price:.2f}')
                self.stop_order = None
                self.tp_order = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.stop_order = None
            return
        if order is self.tp_order:
            if order.status == order.Completed:
                self.log(f'take-profit filled price={order.executed.price:.2f}')
                self.tp_order = None
                self.stop_order = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.tp_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
        self._cancel_exit_orders()
