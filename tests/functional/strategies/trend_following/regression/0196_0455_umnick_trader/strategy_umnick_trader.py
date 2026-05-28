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


class UmnickTraderStrategy(bt.Strategy):
    params = dict(
        stop_base=0.0170,
        lot=0.1,
        spread=0.0005,
    )

    def __init__(self):
        self.current_buy_sell = 1
        self.price_prev = 0.0
        self.array_profit = [0.0] * 8
        self.array_loss = [0.0] * 8
        self.current_index = 0
        self.drawdown = 0.0
        self.max_profit = 0.0
        self.entry_price = None
        self.entry_order = None
        self.exit_order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def next(self):
        self.bar_num += 1
        if len(self.data) < 2:
            return

        if self.position:
            self._update_excursions()
            return

        if self.entry_order is not None or self.exit_order_refs:
            return

        typical_price = (
            float(self.data.open[-1])
            + float(self.data.high[-1])
            + float(self.data.low[-1])
            + float(self.data.close[-1])
        ) / 4.0
        if abs(typical_price - self.price_prev) < self.p.stop_base:
            return
        self.price_prev = typical_price

        limit = self.p.stop_base
        stop = self.p.stop_base
        sum_profit = sum(self.array_profit)
        sum_loss = sum(self.array_loss)
        if sum_profit > self.p.stop_base / 2.0:
            limit = sum_profit / 8.0
        if sum_loss > self.p.stop_base / 2.0:
            stop = sum_loss / 8.0

        close_price = float(self.data.close[0])
        if self.current_buy_sell == 1:
            orders = self.buy_bracket(
                size=self.p.lot,
                exectype=bt.Order.Market,
                stopprice=close_price - stop,
                limitprice=close_price + limit,
            )
        else:
            orders = self.sell_bracket(
                size=self.p.lot,
                exectype=bt.Order.Market,
                stopprice=close_price + stop,
                limitprice=close_price - limit,
            )
        self.entry_order = orders[0]
        self.exit_order_refs = {orders[1].ref, orders[2].ref}

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if self.entry_order is not None and order.ref == self.entry_order.ref:
            if order.status == bt.Order.Completed:
                self.entry_price = order.executed.price
                if order.isbuy() and order.executed.size > 0:
                    self.buy_count += 1
                elif order.issell() and order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.exit_order_refs.clear()
            self.entry_order = None
            return

        if order.ref in self.exit_order_refs and order.status in [
            bt.Order.Completed,
            bt.Order.Canceled,
            bt.Order.Margin,
            bt.Order.Rejected,
            bt.Order.Expired,
        ]:
            self.exit_order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
            self.array_profit[self.current_index] = self.max_profit - self.p.spread * 3.0
            self.array_loss[self.current_index] = self.p.stop_base + self.p.spread * 7.0
        else:
            self.loss_count += 1
            self.array_profit[self.current_index] = self.p.stop_base - self.p.spread * 3.0
            self.array_loss[self.current_index] = self.drawdown + self.p.spread * 7.0
            self.current_buy_sell *= -1
        self.current_index = (self.current_index + 1) % 8
        self.max_profit = 0.0
        self.drawdown = 0.0
        self.entry_price = None

    def _update_excursions(self):
        if self.entry_price is None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            self.max_profit = max(self.max_profit, high - self.entry_price)
            self.drawdown = max(self.drawdown, self.entry_price - low)
        elif self.position.size < 0:
            self.max_profit = max(self.max_profit, self.entry_price - low)
            self.drawdown = max(self.drawdown, high - self.entry_price)
