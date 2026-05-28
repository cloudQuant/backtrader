from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TwentyTwoHundredSimpleStrategy(bt.Strategy):
    params = dict(
        take_profit_points=200,
        stop_loss_points=2000,
        trade_hour=18,
        t1=7,
        t2=2,
        delta=70,
        lot=0.1,
        point=0.01,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.h1 = self.datas[1]
        self.cantrade = True
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.entry_order_ref = None
        self.stop_order = None
        self.stop_order_ref = None
        self.limit_order = None
        self.limit_order_ref = None

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _has_pending_orders(self):
        return any(order is not None for order in (self.entry_order, self.stop_order, self.limit_order))

    def _reset_orders(self):
        self.entry_order = None
        self.entry_order_ref = None
        self.stop_order = None
        self.stop_order_ref = None
        self.limit_order = None
        self.limit_order_ref = None

    def _entry_prices(self, is_long):
        price = float(self.base.close[0])
        stop_distance = float(self.p.stop_loss_points) * float(self.p.point)
        take_distance = float(self.p.take_profit_points) * float(self.p.point)
        if is_long:
            return price - stop_distance, price + take_distance
        return price + stop_distance, price - take_distance

    def _signal_open_buy(self):
        op1 = float(self.h1.open[-self.p.t1])
        op2 = float(self.h1.open[-self.p.t2])
        return (op1 + self.p.delta * self.p.point) < op2

    def _signal_open_sell(self):
        op1 = float(self.h1.open[-self.p.t1])
        op2 = float(self.h1.open[-self.p.t2])
        return op1 > (op2 + self.p.delta * self.p.point)

    def next(self):
        self.bar_num += 1
        if len(self.h1) <= max(self.p.t1, self.p.t2) + 1:
            return

        dt = bt.num2date(self.base.datetime[0])
        if dt.hour > self.p.trade_hour:
            self.cantrade = True

        if self.position or self._has_pending_orders():
            return
        if not self.cantrade or dt.hour != self.p.trade_hour:
            return

        open_buy = self._signal_open_buy()
        open_sell = self._signal_open_sell()
        if open_buy == open_sell:
            return

        size = abs(float(self.p.lot))
        self.signal_count += 1
        self.cantrade = False

        if open_buy:
            stop_price, limit_price = self._entry_prices(is_long=True)
            self.log(
                f'buy size={size:.2f} h1_open_t1={float(self.h1.open[-self.p.t1]):.2f} '
                f'h1_open_t2={float(self.h1.open[-self.p.t2]):.2f} stop={stop_price:.2f} limit={limit_price:.2f}'
            )
            orders = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=stop_price, limitprice=limit_price)
        else:
            stop_price, limit_price = self._entry_prices(is_long=False)
            self.log(
                f'sell size={size:.2f} h1_open_t1={float(self.h1.open[-self.p.t1]):.2f} '
                f'h1_open_t2={float(self.h1.open[-self.p.t2]):.2f} stop={stop_price:.2f} limit={limit_price:.2f}'
            )
            orders = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=stop_price, limitprice=limit_price)

        self.entry_order, self.stop_order, self.limit_order = orders
        self.entry_order_ref = self.entry_order.ref if self.entry_order is not None else None
        self.stop_order_ref = self.stop_order.ref if self.stop_order is not None else None
        self.limit_order_ref = self.limit_order.ref if self.limit_order is not None else None

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if self.entry_order_ref is not None and order.ref == self.entry_order_ref:
            if order.status == bt.Order.Completed:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.log(f'entry filled price={order.executed.price:.2f} size={order.executed.size:.2f}')
            elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.cantrade = True
                self.log(f'entry failed status={order.getstatusname()}')
            if order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
                self.entry_order = None
                self.entry_order_ref = None
            return

        if self.stop_order_ref is not None and order.ref == self.stop_order_ref:
            if order.status == bt.Order.Completed:
                self.log(f'stop filled price={order.executed.price:.2f}')
            if order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
                self.stop_order = None
                self.stop_order_ref = None
            return

        if self.limit_order_ref is not None and order.ref == self.limit_order_ref:
            if order.status == bt.Order.Completed:
                self.log(f'take profit filled price={order.executed.price:.2f}')
            if order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
                self.limit_order = None
                self.limit_order_ref = None
            return

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._reset_orders()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
