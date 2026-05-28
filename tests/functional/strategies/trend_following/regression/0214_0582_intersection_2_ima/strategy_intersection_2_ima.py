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


class Intersection2IMAStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        fast_per=4,
        slow_per=18,
        trailing_stop=20,
        close_half=True,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.fast = bt.indicators.ExponentialMovingAverage(self.data.close, period=int(self.p.fast_per))
        self.slow = bt.indicators.ExponentialMovingAverage(self.data.close, period=int(self.p.slow_per))
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

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _trail(self):
        if not self.position or self.order is not None or float(self.p.trailing_stop) <= 0:
            return
        ts = float(self.p.trailing_stop) * self._point()
        current = float(self.data.close[0])
        if self.position.size > 0:
            new_sl = self._round(current - ts)
            if self.stop_price is None or new_sl > float(self.stop_price):
                self.stop_price = new_sl
        else:
            new_sl = self._round(current + ts)
            if self.stop_price is None or new_sl < float(self.stop_price):
                self.stop_price = new_sl

    def _check_exit(self):
        if not self.position or self.order is not None or self.stop_price is None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0 and low <= float(self.stop_price):
            self.order = self.close(); return
        if self.position.size < 0 and high >= float(self.stop_price):
            self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self) < max(int(self.p.fast_per), int(self.p.slow_per)) + 4:
            return
        if self.order is not None:
            return

        if self.position:
            self._trail()
            self._check_exit()
            if self.order is not None:
                return

        ma_fast1 = float(self.fast[-1])
        ma_fast3 = float(self.fast[-3])
        ma_slow1 = float(self.slow[-1])
        ma_slow3 = float(self.slow[-3])

        buy_op = ma_fast1 < ma_slow1 and ma_fast3 > ma_slow3
        sell_op = ma_fast1 > ma_slow1 and ma_fast3 < ma_slow3

        if buy_op:
            if self.position.size < 0:
                self.order = self.close()
            elif not self.position:
                self.signal_count += 1
                self.order = self.buy(size=float(self.p.lots))
            return

        if sell_op:
            if self.position.size > 0:
                self.order = self.close()
            elif not self.position:
                self.signal_count += 1
                self.order = self.sell(size=float(self.p.lots))

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
                self.stop_price = None
            else:
                self.stop_price = None
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
