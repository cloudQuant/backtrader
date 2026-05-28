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


class BreakthroughBbStrategy(bt.Strategy):
    params = dict(
        ma_period=9,
        bands_period=28,
        deviation=1.6,
        lot=0.1,
    )

    def __init__(self):
        self.ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.ma_period)
        self.bbands = bt.indicators.BollingerBands(self.data.close, period=self.p.bands_period, devfactor=self.p.deviation)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.bands_period, self.p.ma_period) + 5
        if len(self.data) < warmup:
            return
        if self.order:
            return

        close_1 = float(self.data.close[-1])
        close_4 = float(self.data.close[-4])
        bb_mid_1 = float(self.bbands.mid[-1])
        bb_up_1 = float(self.bbands.top[-1])
        bb_low_1 = float(self.bbands.bot[-1])
        ma_1 = float(self.ma[-1])
        ma_4 = float(self.ma[-4])

        if self.position:
            if self.position.size > 0 and close_1 < bb_mid_1:
                self.order = self.close()
                return
            if self.position.size < 0 and close_1 > bb_mid_1:
                self.order = self.close()
                return
            return

        if close_4 < bb_up_1 and close_1 > bb_up_1 and ma_1 > ma_4:
            self.order = self.buy(size=self.p.lot)
            return

        if close_4 > bb_low_1 and close_1 < bb_low_1 and ma_1 < ma_4:
            self.order = self.sell(size=self.p.lot)
            return

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
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
