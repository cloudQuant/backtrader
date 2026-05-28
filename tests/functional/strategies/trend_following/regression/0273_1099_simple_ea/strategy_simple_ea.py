from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader.feeds as btfeeds
from backtrader.strategy import Strategy
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


class SimpleEAStrategy(Strategy):
    params = dict(
        lot=0.1,
        tp_points=46,
        sl_points=31,
        point=0.01,
    )

    def __init__(self):
        self.next_direction = 1
        self.entry_price = None
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.pending_entry_direction = 0

    def _open_pending_direction(self):
        if self.next_direction > 0:
            self.buy_signal_count += 1
            self.pending_entry_direction = 1
            self.buy(size=self.p.lot)
        else:
            self.sell_signal_count += 1
            self.pending_entry_direction = -1
            self.sell(size=self.p.lot)

    def next(self):
        if not self.position:
            self._open_pending_direction()
            return

        if self.entry_price is None:
            return

        high = float(self.data.high[0])
        low = float(self.data.low[0])
        tp_distance = float(self.p.tp_points) * float(self.p.point)
        sl_distance = float(self.p.sl_points) * float(self.p.point)

        if self.position.size > 0:
            if high >= self.entry_price + tp_distance:
                self.next_direction = 1
                self.close()
                return
            if low <= self.entry_price - sl_distance:
                self.next_direction = -1
                self.close()
                return
        else:
            if low <= self.entry_price - tp_distance:
                self.next_direction = -1
                self.close()
                return
            if high >= self.entry_price + sl_distance:
                self.next_direction = 1
                self.close()
                return

    def notify_order(self, order):
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.pending_entry_direction = 0
            return

        if order.status != order.Completed:
            return

        self.completed_order_count += 1

        if self.pending_entry_direction == 1 and order.isbuy():
            self.buy_count += 1
            self.entry_price = order.executed.price
            self.pending_entry_direction = 0
            return

        if self.pending_entry_direction == -1 and order.issell():
            self.sell_count += 1
            self.entry_price = order.executed.price
            self.pending_entry_direction = 0
            return

        if not self.position:
            self.entry_price = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
