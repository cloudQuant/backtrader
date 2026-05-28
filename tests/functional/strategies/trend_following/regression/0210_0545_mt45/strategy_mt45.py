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


class MT45Strategy(bt.Strategy):
    params = dict(
        stop=600,
        take=700,
        lt=0.01,
        kl=2.0,
        ml=10.0,
        point=0.0001,
        price_digits=5,
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
        self.stop_price = None
        self.take_profit_price = None
        self.next_direction = 'buy'
        self.current_lot = float(self.p.lt)

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _arm(self, direction, price):
        sl = float(self.p.stop) * self._point()
        tp = float(self.p.take) * self._point()
        if direction == 'buy':
            self.stop_price = self._round(price - sl)
            self.take_profit_price = self._round(price + tp)
            self.signal_count += 1
            self.order = self.buy(size=self.current_lot)
        else:
            self.stop_price = self._round(price + sl)
            self.take_profit_price = self._round(price - tp)
            self.signal_count += 1
            self.order = self.sell(size=self.current_lot)

    def _check_exit(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if low <= float(self.stop_price):
                self.order = self.close(); return
            if high >= float(self.take_profit_price):
                self.order = self.close(); return
        else:
            if high >= float(self.stop_price):
                self.order = self.close(); return
            if low <= float(self.take_profit_price):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self.position:
            self._check_exit()
            return
        self._arm(self.next_direction, float(self.data.close[0]))

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
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.next_direction = 'sell' if self.next_direction == 'buy' else 'buy'
        if trade.pnlcomm >= 0:
            self.win_count += 1
            self.current_lot = float(self.p.lt)
        else:
            self.loss_count += 1
            self.current_lot = self.current_lot * float(self.p.kl)
            if self.current_lot > float(self.p.ml):
                self.current_lot = float(self.p.lt)
