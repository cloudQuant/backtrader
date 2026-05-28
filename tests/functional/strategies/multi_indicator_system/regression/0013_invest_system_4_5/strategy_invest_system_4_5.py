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


class InvestSystem45Strategy(bt.Strategy):
    params = dict(
        stop_loss_pips=240,
        take_profit_pips=40,
        point=0.01,
        current_tf_compression=15,
        higher_tf_compression=240,
        lots1=0.1,
        lots2=0.2,
        lots3=0.7,
        lots4=1.4,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.data1 = self.datas[1]
        self.stop_loss = self.p.stop_loss_pips * self.p.point
        self.take_profit = self.p.take_profit_pips * self.p.point

        self.work = True
        self.opn_b = False
        self.opn_s = False
        self.vhod = False
        self.lts = False
        self.plan_b = False
        self.l2_stop = True
        self.l3_stop = True
        self.l4_stop = True
        self.l5_stop = True
        self.l6_stop = True

        self.chas = None
        self.pribl = -1.0
        self.current_lots = None
        self.max_balance = 0.1
        self.min_balance = None

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
        if len(self.data1) < 2:
            return
        if self.entry_order is not None or self.exit_order_refs:
            return

        balance = self.broker.getcash()
        if self.min_balance is None:
            self.min_balance = balance
        self._update_lot_thresholds(balance)

        lot1 = self.p.lots1
        lot2 = self.p.lots3
        if self.current_lots is None:
            self.current_lots = lot1

        if self.position:
            self.lts = True

        if not self.position and balance > self.max_balance:
            self.plan_b = False
            lot1 = self.p.lots1
            lot2 = self.p.lots3
            self.max_balance = balance
        if not self.position and self.plan_b:
            lot1 = self.p.lots2
            lot2 = self.p.lots4
        if self.lts and not self.position and self.pribl < 0 and self._same_lot(self.current_lots, lot2):
            self.plan_b = True
            self.lts = False
        if self.lts and not self.position and self.pribl < 0 and self._same_lot(self.current_lots, lot1):
            self.current_lots = lot2
            self.lts = False
        if self.lts and not self.position and self.pribl > 0:
            self.current_lots = lot1
            self.lts = False
        if self.lts and not self.position and self.pribl < 0:
            self.current_lots = lot2
            self.lts = False

        prev_h4_open = float(self.data1.open[-1])
        prev_h4_close = float(self.data1.close[-1])
        if prev_h4_close > prev_h4_open:
            self.opn_s = False
            self.opn_b = True
        elif prev_h4_close < prev_h4_open:
            self.opn_s = True
            self.opn_b = False

        if self.position:
            self.vhod = False

        h4_dt = bt.num2date(self.data1.datetime[0])
        if self.chas != h4_dt:
            self.chas = h4_dt
            self.vhod = True

        current_dt = bt.num2date(self.data0.datetime[0])
        if current_dt.minute > 15:
            return
        if self.position or not self.vhod or not self.work:
            return

        close_price = float(self.data0.close[0])
        if self.opn_b:
            orders = self.buy_bracket(
                size=self.current_lots,
                exectype=bt.Order.Market,
                stopprice=close_price - self.stop_loss,
                limitprice=close_price + self.take_profit,
            )
            self.entry_order = orders[0]
            self.exit_order_refs = {orders[1].ref, orders[2].ref}
            self.vhod = False
            return

        if self.opn_s:
            orders = self.sell_bracket(
                size=self.current_lots,
                exectype=bt.Order.Market,
                stopprice=close_price + self.stop_loss,
                limitprice=close_price - self.take_profit,
            )
            self.entry_order = orders[0]
            self.exit_order_refs = {orders[1].ref, orders[2].ref}
            self.vhod = False

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if self.entry_order is not None and order.ref == self.entry_order.ref:
            if order.status == bt.Order.Completed:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
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
        self.pribl = trade.pnlcomm
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1

    def _update_lot_thresholds(self, balance):
        if balance > (self.min_balance * 2) and self.l2_stop:
            self.p.lots1 = 0.2
            self.p.lots2 = 0.4
            self.p.lots3 = 1.4
            self.p.lots4 = 2.8
            self.l2_stop = False
        if balance > (self.min_balance * 3) and self.l3_stop:
            self.p.lots1 = 0.3
            self.p.lots2 = 0.6
            self.p.lots3 = 2.1
            self.p.lots4 = 4.2
            self.l3_stop = False
        if balance > (self.min_balance * 4) and self.l4_stop:
            self.p.lots1 = 0.4
            self.p.lots2 = 0.8
            self.p.lots3 = 2.8
            self.p.lots4 = 5.6
            self.l4_stop = False
        if balance > (self.min_balance * 5) and self.l5_stop:
            self.p.lots1 = 0.5
            self.p.lots2 = 1.0
            self.p.lots3 = 3.5
            self.p.lots4 = 7.0
            self.l5_stop = False
        if balance > (self.min_balance * 6) and self.l6_stop:
            self.p.lots1 = 0.6
            self.p.lots2 = 1.2
            self.p.lots3 = 4.2
            self.p.lots4 = 8.4
            self.l6_stop = False

    @staticmethod
    def _same_lot(left, right, tol=1e-9):
        return abs(left - right) <= tol
