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


class SimpleThreeInsidePatternStrategy(bt.Strategy):
    params = dict(
        stop_loss=500,
        take_profit=500,
        lot=0.1,
        magic_number=3119,
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
    )

    def __init__(self):
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_orders = []
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self):
        lot = min(max(self.p.lot, self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def bullish_three_inside(self):
        older_open = float(self.data.open[-2])
        older_close = float(self.data.close[-2])
        older_high = float(self.data.high[-2])
        older_low = float(self.data.low[-2])
        middle_open = float(self.data.open[-1])
        middle_close = float(self.data.close[-1])
        latest_open = float(self.data.open[0])
        latest_close = float(self.data.close[0])
        return (
            older_open > older_close and
            middle_open < middle_close and
            middle_open > older_low and
            middle_close < older_high and
            latest_open < latest_close and
            latest_open > middle_open and
            latest_open < middle_close and
            latest_close > older_high
        )

    def bearish_three_inside(self):
        older_open = float(self.data.open[-2])
        older_close = float(self.data.close[-2])
        older_high = float(self.data.high[-2])
        older_low = float(self.data.low[-2])
        middle_open = float(self.data.open[-1])
        middle_close = float(self.data.close[-1])
        latest_open = float(self.data.open[0])
        latest_close = float(self.data.close[0])
        return (
            older_open < older_close and
            middle_open > middle_close and
            middle_open < older_high and
            middle_close > older_low and
            latest_open > latest_close and
            latest_open < middle_open and
            latest_open > middle_close and
            latest_close < older_low
        )

    def next(self):
        self.bar_num += 1
        if len(self.data) < 3:
            return
        if self.position or self.entry_order is not None:
            return
        size = self._normalize_lot()
        if self.bullish_three_inside():
            close_price = float(self.data.close[0])
            sl = close_price - self.p.stop_loss * self.p.point_size
            tp = close_price + self.p.take_profit * self.p.point_size
            orders = self.buy_bracket(size=size, stopprice=sl, limitprice=tp)
            self.entry_order, self.stop_order, self.limit_order = orders
            self.pending_orders = list(orders)
            self.entry_order.addinfo(kind='entry_long')
            self.buy_count += 1
            return
        if self.bearish_three_inside():
            close_price = float(self.data.close[0])
            sl = close_price + self.p.stop_loss * self.p.point_size
            tp = close_price - self.p.take_profit * self.p.point_size
            orders = self.sell_bracket(size=size, stopprice=sl, limitprice=tp)
            self.entry_order, self.stop_order, self.limit_order = orders
            self.pending_orders = list(orders)
            self.entry_order.addinfo(kind='entry_short')
            self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        kind = getattr(order.info, 'kind', None)
        if order.status == order.Completed:
            if kind == 'entry_long':
                entry_price = order.executed.price
                sl = self.stop_order.created.price if self.stop_order is not None else float('nan')
                tp = self.limit_order.created.price if self.limit_order is not None else float('nan')
                self.log(f'long entry price={entry_price:.2f} sl={sl:.2f} tp={tp:.2f}')
            elif kind == 'entry_short':
                entry_price = order.executed.price
                sl = self.stop_order.created.price if self.stop_order is not None else float('nan')
                tp = self.limit_order.created.price if self.limit_order is not None else float('nan')
                self.log(f'short entry price={entry_price:.2f} sl={sl:.2f} tp={tp:.2f}')
        else:
            pass

        if order in self.pending_orders and not order.alive():
            self.pending_orders = [o for o in self.pending_orders if o is not order and o.alive()]
        if order is self.entry_order and not order.alive():
            self.entry_order = None
        if order is self.stop_order and not order.alive():
            self.stop_order = None
        if order is self.limit_order and not order.alive():
            self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_orders = []
