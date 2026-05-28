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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
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


class PROphetStrategy(bt.Strategy):
    params = dict(
        da_buy=True,
        x1=9,
        x2=29,
        x3=94,
        x4=125,
        slb=68,
        da_sell=True,
        y1=61,
        y2=100,
        y3=117,
        y4=31,
        sls=72,
        lot=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        spread_buffer=2,
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
        self.last_trade_bar_dt = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _qu(self, q1, q2, q3, q4):
        return (
            (q1 - 100) * abs(float(self.data.high[-1]) - float(self.data.low[-2])) +
            (q2 - 100) * abs(float(self.data.high[-3]) - float(self.data.low[-2])) +
            (q3 - 100) * abs(float(self.data.high[-2]) - float(self.data.low[-1])) +
            (q4 - 100) * abs(float(self.data.high[-2]) - float(self.data.low[-3]))
        )

    def _manage_buy(self, dt):
        if not self.position or self.position.size <= 0:
            return False
        unit = self._unit()
        if dt.hour > 18:
            self.order = self.close()
            return True
        threshold = (self.stop_price if self.stop_price is not None else self.position.price - float(self.p.slb) * unit) + float(self.p.spread_buffer) * unit
        if float(self.data.close[0]) > threshold:
            self.stop_price = round(float(self.data.close[0]) - float(self.p.slb) * unit, int(self.p.price_digits))
        if self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
            self.order = self.close()
            return True
        return False

    def _manage_sell(self, dt):
        if not self.position or self.position.size >= 0:
            return False
        unit = self._unit()
        if dt.hour > 18:
            self.order = self.close()
            return True
        threshold = (self.stop_price if self.stop_price is not None else self.position.price + float(self.p.sls) * unit) - float(self.p.spread_buffer) * unit
        if float(self.data.close[0]) < threshold:
            self.stop_price = round(float(self.data.close[0]) + float(self.p.sls) * unit, int(self.p.price_digits))
        if self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
            self.order = self.close()
            return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < 5:
            return
        if self.order is not None:
            return
        dt = bt.num2date(self.data.datetime[0])
        if self.position:
            if self.position.size > 0 and self.p.da_buy and self._manage_buy(dt):
                return
            if self.position.size < 0 and self.p.da_sell and self._manage_sell(dt):
                return
            return
        if self.last_trade_bar_dt == dt:
            return
        if self.p.da_buy and 10 <= dt.hour <= 18 and self._qu(self.p.x1, self.p.x2, self.p.x3, self.p.x4) > 0:
            self.signal_count += 1
            unit = self._unit()
            self.stop_price = round(float(self.data.close[0]) - float(self.p.slb) * unit, int(self.p.price_digits))
            self.order = self.buy(size=self.p.lot)
            self.last_trade_bar_dt = dt
            return
        if self.p.da_sell and 10 <= dt.hour <= 18 and self._qu(self.p.y1, self.p.y2, self.p.y3, self.p.y4) > 0:
            self.signal_count += 1
            unit = self._unit()
            self.stop_price = round(float(self.data.close[0]) + float(self.p.sls) * unit, int(self.p.price_digits))
            self.order = self.sell(size=self.p.lot)
            self.last_trade_bar_dt = dt

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
