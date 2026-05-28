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


class MacdSimpleReshetovStrategy(bt.Strategy):
    params = dict(
        lot=2.0,
        df=1,
        ds=2,
        signal_period=10,
    )

    def __init__(self):
        fast_period = self.p.signal_period + self.p.df
        slow_period = self.p.signal_period + self.p.df + self.p.ds
        self.macd = bt.ind.MACD(
            self.data.close,
            period_me1=fast_period,
            period_me2=slow_period,
            period_signal=self.p.signal_period,
        )
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.signal_period + self.p.df + self.p.ds + 2:
            return
        if self.order:
            return

        main = float(self.macd.macd[0])
        signal = float(self.macd.signal[0])
        if main != main or signal != signal:
            return

        if self.position:
            if self.position.size > 0 and main < 0:
                self.order = self.close()
            elif self.position.size < 0 and main > 0:
                self.order = self.close()
            return

        if main * signal <= 0:
            return
        if main > 0:
            if main > signal:
                self.order = self.buy(size=self.p.lot)
            return
        if main < signal:
            self.order = self.sell(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and order.executed.size > 0:
                self.buy_count += 1
            elif order.issell() and order.executed.size < 0:
                self.sell_count += 1
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
