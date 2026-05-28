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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume']
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class FractalsMinimumDistanceStrategy(bt.Strategy):
    params = dict(
        distance=15,
        signal_bar=3,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.pending_direction = None
        self.prev_upper = None
        self.prev_lower = None

    def _point(self):
        return float(self.p.point)

    def _is_upper_fractal(self, idx):
        if len(self) < idx + 3:
            return False
        h = float(self.data.high[-idx])
        return h > float(self.data.high[-idx - 1]) and h > float(self.data.high[-idx - 2]) and h > float(self.data.high[-idx + 1]) and h > float(self.data.high[-idx + 2])

    def _is_lower_fractal(self, idx):
        if len(self) < idx + 3:
            return False
        l = float(self.data.low[-idx])
        return l < float(self.data.low[-idx - 1]) and l < float(self.data.low[-idx - 2]) and l < float(self.data.low[-idx + 1]) and l < float(self.data.low[-idx + 2])

    def next(self):
        self.bar_num += 1
        idx = int(self.p.signal_bar)
        if len(self) < idx + 3:
            return
        if self.order is not None:
            return

        if not self.position and self.pending_direction is not None:
            if self.pending_direction == 'buy':
                self.signal_count += 1
                self.order = self.buy(size=self.p.lots)
            else:
                self.signal_count += 1
                self.order = self.sell(size=self.p.lots)
            self.pending_direction = None
            return

        if self._is_upper_fractal(idx):
            self.prev_upper = float(self.data.high[-idx])
            if self.prev_lower is None or abs(self.prev_upper - self.prev_lower) < float(self.p.distance) * self._point():
                return
            if self.position.size > 0:
                self.pending_direction = 'sell'
                self.order = self.close()
                return
            if self.position.size == 0:
                self.signal_count += 1
                self.order = self.sell(size=self.p.lots)
                return

        if self._is_lower_fractal(idx):
            self.prev_lower = float(self.data.low[-idx])
            if self.prev_upper is None or abs(self.prev_upper - self.prev_lower) < float(self.p.distance) * self._point():
                return
            if self.position.size < 0:
                self.pending_direction = 'buy'
                self.order = self.close()
                return
            if self.position.size == 0:
                self.signal_count += 1
                self.order = self.buy(size=self.p.lots)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
