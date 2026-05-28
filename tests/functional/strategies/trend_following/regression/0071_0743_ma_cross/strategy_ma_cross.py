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


def applied_price(data, mode):
    mode = str(mode).upper()
    if mode == 'PRICE_OPEN':
        return data.open
    if mode == 'PRICE_HIGH':
        return data.high
    if mode == 'PRICE_LOW':
        return data.low
    if mode == 'PRICE_MEDIAN':
        return (data.high + data.low) / 2.0
    if mode == 'PRICE_TYPICAL':
        return (data.high + data.low + data.close) / 3.0
    if mode == 'PRICE_WEIGHTED':
        return (data.high + data.low + 2.0 * data.close) / 4.0
    return data.close


def ma_indicator(source, period, method):
    method = str(method).upper()
    if method == 'MODE_EMA':
        return bt.indicators.ExponentialMovingAverage(source, period=period)
    if method == 'MODE_SMMA':
        return bt.indicators.SmoothedMovingAverage(source, period=period)
    if method == 'MODE_LWMA':
        return bt.indicators.WeightedMovingAverage(source, period=period)
    return bt.indicators.SimpleMovingAverage(source, period=period)


class MACrossStrategy(bt.Strategy):
    params = dict(
        ma_1_period=3,
        ma_2_period=13,
        ma_1_method='MODE_SMA',
        ma_2_method='MODE_LWMA',
        ma_1_price='PRICE_CLOSE',
        ma_2_price='PRICE_MEDIAN',
        ma_1_shift=0,
        ma_2_shift=0,
        lot=0.1,
    )

    def __init__(self):
        src1 = applied_price(self.data, self.p.ma_1_price)
        src2 = applied_price(self.data, self.p.ma_2_price)
        self.ma1 = ma_indicator(src1, self.p.ma_1_period, self.p.ma_1_method)
        self.ma2 = ma_indicator(src2, self.p.ma_2_period, self.p.ma_2_method)

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

    def _cross_open(self):
        ma1_0 = float(self.ma1[0])
        ma1_1 = float(self.ma1[-1])
        ma2_0 = float(self.ma2[0])
        if (ma1_1 <= ma2_0 and ma1_0 > ma2_0) or (ma1_1 < ma2_0 and ma1_0 >= ma2_0):
            return 1
        if (ma1_1 >= ma2_0 and ma1_0 < ma2_0) or (ma1_1 > ma2_0 and ma1_0 <= ma2_0):
            return 2
        return 0

    def _cross_close(self):
        ma1_0 = float(self.ma1[0])
        ma1_1 = float(self.ma1[-1])
        ma2_0 = float(self.ma2[0])
        if (ma1_1 >= ma2_0 and ma1_0 < ma2_0) or (ma1_1 > ma2_0 and ma1_0 <= ma2_0):
            return 1
        if (ma1_1 <= ma2_0 and ma1_0 > ma2_0) or (ma1_1 < ma2_0 and ma1_0 >= ma2_0):
            return 2
        return 0

    def next(self):
        self.bar_num += 1
        if len(self) < max(int(self.p.ma_1_period), int(self.p.ma_2_period)) + 2:
            return
        if self.order is not None:
            return
        if self.position.size > 0 and self._cross_close() == 1:
            self.order = self.close()
            return
        if self.position.size < 0 and self._cross_close() == 2:
            self.order = self.close()
            return
        signal = self._cross_open()
        if signal == 1:
            if self.position.size < 0:
                self.order = self.close()
                return
            if not self.position:
                self.signal_count += 1
                self.order = self.buy(size=self.p.lot)
                return
        if signal == 2:
            if self.position.size > 0:
                self.order = self.close()
                return
            if not self.position:
                self.signal_count += 1
                self.order = self.sell(size=self.p.lot)

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
