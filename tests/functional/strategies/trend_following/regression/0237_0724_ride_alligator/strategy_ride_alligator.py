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


class RideAlligatorStrategy(bt.Strategy):
    params = dict(
        alligator_period=5,
        risk_factor=0.5,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        min_lot=0.01,
        max_lot=100.0,
    )

    def __init__(self):
        period = int(self.p.alligator_period)
        a1 = max(1, int(round(period * 1.61803398874989)))
        a2 = max(1, int(round(a1 * 1.61803398874989)))
        a3 = max(1, int(round(a2 * 1.61803398874989)))
        median = (self.data.high + self.data.low) / 2.0
        self.lips = bt.indicators.WeightedMovingAverage(median, period=period)
        self.teeth = bt.indicators.WeightedMovingAverage(median, period=a1)
        self.jaws = bt.indicators.WeightedMovingAverage(median, period=a3)

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

    def _calc_lot(self):
        min_lot = float(self.p.min_lot)
        max_lot = float(self.p.max_lot)
        lot = self.broker.getvalue() * float(self.p.risk_factor) / 100.0 / 100.0
        return max(min_lot, min(max_lot, round(lot, 2)))

    def next(self):
        self.bar_num += 1
        if len(self) < 20:
            return
        if self.order is not None:
            return
        lips_now = float(self.lips[0])
        lips_pre = float(self.lips[-1])
        jaws_now = float(self.jaws[0])
        jaws_pre = float(self.jaws[-1])
        teeth_now = float(self.teeth[0])
        lot = self._calc_lot()
        if self.position:
            if self.position.size > 0:
                if jaws_now < float(self.data.close[0]):
                    new_stop = round(jaws_now, int(self.p.price_digits))
                    if self.stop_price is None or new_stop > self.stop_price:
                        self.stop_price = new_stop
                if self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
                    self.order = self.close()
                    return
            else:
                if jaws_now > float(self.data.close[0]):
                    new_stop = round(jaws_now, int(self.p.price_digits))
                    if self.stop_price is None or new_stop < self.stop_price:
                        self.stop_price = new_stop
                if self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
                    self.order = self.close()
                    return
            return
        if lips_now > jaws_now and teeth_now < jaws_now and lips_pre < jaws_pre:
            self.signal_count += 1
            self.order = self.buy(size=lot)
            self.stop_price = round(jaws_now, int(self.p.price_digits)) if jaws_now > 0 else None
            return
        if lips_now < jaws_now and teeth_now > jaws_now and lips_pre > jaws_pre:
            self.signal_count += 1
            self.order = self.sell(size=lot)
            self.stop_price = round(jaws_now, int(self.p.price_digits)) if jaws_now > 0 else None

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
