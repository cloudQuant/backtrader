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


class SimplePendingOrdersTimeStrategy(bt.Strategy):
    params = dict(
        trading_start=15,
        end_of_trade=16,
        indent=100,
        stop_loss=200,
        lots=0.1,
        magic_number=9462,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.buy_stop = None
        self.sell_stop = None
        self.last_setup_day = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_price(self, value):
        return round(value, self.p.price_digits)

    def _can_trade(self, dt):
        if self.p.trading_start > self.p.end_of_trade:
            return dt.hour >= self.p.trading_start or dt.hour < self.p.end_of_trade
        return self.p.trading_start <= dt.hour < self.p.end_of_trade

    def _cancel_pending_orders(self):
        for order in (self.buy_stop, self.sell_stop):
            if order is not None and order.alive():
                self.cancel(order)
        self.buy_stop = None
        self.sell_stop = None

    def _close_all_positions(self):
        if self.position:
            self.close()
            self.log('forced close outside trade window')

    def _set_pending_orders(self):
        ask = float(self.data.close[0])
        bid = float(self.data.close[0])
        buy_price = self._round_price(ask + self.p.indent * self.p.point)
        sell_price = self._round_price(bid - self.p.indent * self.p.point)
        buy_sl = self._round_price(buy_price - self.p.stop_loss * self.p.point)
        sell_sl = self._round_price(sell_price + self.p.stop_loss * self.p.point)
        self.buy_stop = self.buy(size=self.p.lots, exectype=bt.Order.Stop, price=buy_price, valid=None)
        self.sell_stop = self.sell(size=self.p.lots, exectype=bt.Order.Stop, price=sell_price, valid=None)
        self.log(f'set pending buy_stop={buy_price:.2f} sl={buy_sl:.2f} sell_stop={sell_price:.2f} sl={sell_sl:.2f}')

    def next(self):
        self.bar_num += 1
        dt = bt.num2date(self.data.datetime[0])
        in_window = self._can_trade(dt)
        if not in_window:
            self._close_all_positions()
            self._cancel_pending_orders()
            return
        if dt.hour == self.p.trading_start and dt.minute == 0 and self.last_setup_day != dt.date():
            if not self.position and self.buy_stop is None and self.sell_stop is None:
                self._set_pending_orders()
                self.last_setup_day = dt.date()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order is self.buy_stop:
            if order.status == order.Completed:
                self.buy_count += 1
                buy_sl = self._round_price(order.executed.price - self.p.stop_loss * self.p.point)
                self.sell_stop = self.sell_stop if self.sell_stop and self.sell_stop.alive() else None
                self.log(f'buy stop filled price={order.executed.price:.2f} sl={buy_sl:.2f}')
                if self.position.size > 0:
                    self.sell(size=abs(self.position.size), exectype=bt.Order.Stop, price=buy_sl)
                self.buy_stop = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.buy_stop = None
            return
        if order is self.sell_stop:
            if order.status == order.Completed:
                self.sell_count += 1
                sell_sl = self._round_price(order.executed.price + self.p.stop_loss * self.p.point)
                self.buy_stop = self.buy_stop if self.buy_stop and self.buy_stop.alive() else None
                self.log(f'sell stop filled price={order.executed.price:.2f} sl={sell_sl:.2f}')
                if self.position.size < 0:
                    self.buy(size=abs(self.position.size), exectype=bt.Order.Stop, price=sell_sl)
                self.sell_stop = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.sell_stop = None
            return

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
                self.log(f'buy stop filled price={trade.price:.2f}')
            elif trade.size < 0:
                self.sell_count += 1
                self.log(f'sell stop filled price={trade.price:.2f}')
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
