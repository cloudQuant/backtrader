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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class OpenTicksStrategy(bt.Strategy):
    params = dict(
        trailing_stop=300,
        stop_loss=300,
        lot=0.1,
        half_lots=True,
        max_orders=1,
        point=0.01,
        price_digits=2,
        min_lot=0.01,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.stop_price = None
        self._position_was_open = False
        self._last_partial_bar = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _buy_signal(self):
        return (
            float(self.data.high[-1]) > float(self.data.high[-2]) > float(self.data.high[-3]) > float(self.data.high[-4])
            and float(self.data.open[-1]) > float(self.data.open[-2]) > float(self.data.open[-3]) > float(self.data.open[-4])
        )

    def _sell_signal(self):
        return (
            float(self.data.high[-1]) < float(self.data.high[-2]) < float(self.data.high[-3]) < float(self.data.high[-4])
            and float(self.data.open[-1]) < float(self.data.open[-2]) < float(self.data.open[-3]) < float(self.data.open[-4])
        )

    def _set_stop(self, is_long, price):
        if self.p.stop_loss == 0:
            self.stop_price = None
            return
        self.stop_price = round(price - self.p.stop_loss * self.p.point, self.p.price_digits) if is_long else round(price + self.p.stop_loss * self.p.point, self.p.price_digits)

    def _maybe_partial_close(self):
        if not self.p.half_lots or self._last_partial_bar == len(self):
            return False
        half_size = round(abs(self.position.size) / 2.0, 2)
        if half_size < self.p.min_lot or half_size >= abs(self.position.size):
            return False
        self.log(f'partial close size={half_size:.2f}')
        self.entry_order = self.close(size=half_size)
        self._last_partial_bar = len(self)
        return True

    def _trailing_stairs(self):
        if not self.position or self.p.trailing_stop <= 0:
            return False
        close_price = round(float(self.data.close[0]), self.p.price_digits)
        if self.position.size > 0:
            if close_price - self.position.price > self.p.trailing_stop * self.p.point:
                new_stop = round(close_price - self.p.trailing_stop * self.p.point, self.p.price_digits)
                if self.stop_price is None or self.stop_price < new_stop:
                    self.stop_price = new_stop
                    self.log(f'update long stop={self.stop_price:.2f}')
                    return self._maybe_partial_close()
                if self.stop_price is not None and self.stop_price >= new_stop:
                    self.log('close long by trailing stair saturation')
                    self.entry_order = self.close()
                    return True
        else:
            if self.position.price - close_price > self.p.trailing_stop * self.p.point:
                new_stop = round(close_price + self.p.trailing_stop * self.p.point, self.p.price_digits)
                if self.stop_price is None or self.stop_price > new_stop:
                    self.stop_price = new_stop
                    self.log(f'update short stop={self.stop_price:.2f}')
                    if self.p.half_lots:
                        return self._maybe_partial_close()
                    self.log('close short by trailing stair')
                    self.entry_order = self.close()
                    return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < 5:
            return
        if self.entry_order is not None:
            return

        high_price = round(float(self.data.high[0]), self.p.price_digits)
        low_price = round(float(self.data.low[0]), self.p.price_digits)
        if self.position:
            if self.position.size > 0 and self.stop_price is not None and low_price <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.2f}')
                self.entry_order = self.close()
                return
            if self.position.size < 0 and self.stop_price is not None and high_price >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.2f}')
                self.entry_order = self.close()
                return
            if self._trailing_stairs():
                return

        buy_op = self._buy_signal()
        sell_op = self._sell_signal()
        if self.position:
            return
        if not (self.position.size == 0 and (self.p.max_orders == 0 or self.p.max_orders >= 1)):
            return

        close_price = round(float(self.data.close[0]), self.p.price_digits)
        if buy_op:
            self.log('buy monotonic 4-bar pattern')
            self._set_stop(True, close_price)
            self.entry_order = self.buy(size=self.p.lot)
            return
        if sell_op:
            self.log('sell monotonic 4-bar pattern')
            self._set_stop(False, close_price)
            self.entry_order = self.sell(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.log(f'entry filled price={order.executed.price:.2f} size={order.executed.size:.2f}')
            else:
                self.log(f'position closed price={order.executed.price:.2f} size={order.executed.size:.2f}')
                self.stop_price = None
                self._last_partial_bar = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
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
