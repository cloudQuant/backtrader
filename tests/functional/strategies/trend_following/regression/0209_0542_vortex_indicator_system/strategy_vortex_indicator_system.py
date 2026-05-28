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


class VortexIndicator(bt.Indicator):
    lines = ('plus_vi', 'minus_vi')
    params = (('period', 14),)

    def __init__(self):
        tr = bt.Max(self.data.high - self.data.low, abs(self.data.high - self.data.close(-1)), abs(self.data.low - self.data.close(-1)))
        plus_vm = abs(self.data.high - self.data.low(-1))
        minus_vm = abs(self.data.low - self.data.high(-1))
        sum_tr = bt.ind.SumN(tr, period=self.p.period)
        sum_plus_vm = bt.ind.SumN(plus_vm, period=self.p.period)
        sum_minus_vm = bt.ind.SumN(minus_vm, period=self.p.period)
        self.l.plus_vi = bt.If(sum_tr != 0, sum_plus_vm / sum_tr, 0.0)
        self.l.minus_vi = bt.If(sum_tr != 0, sum_minus_vm / sum_tr, 0.0)


class VortexIndicatorSystemStrategy(bt.Strategy):
    params = dict(
        vi_length=14,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.vortex = VortexIndicator(self.data, period=int(self.p.vi_length))
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
        self.buy_setup = False
        self.sell_setup = False
        self.entry_trigger = None

    def next(self):
        self.bar_num += 1
        if len(self) < int(self.p.vi_length) + 3 or self.order is not None:
            return

        plus1 = float(self.vortex.plus_vi[-1])
        plus2 = float(self.vortex.plus_vi[-2])
        minus1 = float(self.vortex.minus_vi[-1])
        minus2 = float(self.vortex.minus_vi[-2])

        if plus2 <= minus2 and plus1 > minus1:
            if self.position.size < 0:
                self.order = self.close()
                self.buy_setup = True
                self.sell_setup = False
                self.entry_trigger = float(self.data.high[-1])
                return
            self.buy_setup = True
            self.sell_setup = False
            self.entry_trigger = float(self.data.high[-1])
        elif minus2 <= plus2 and minus1 > plus1:
            if self.position.size > 0:
                self.order = self.close()
                self.sell_setup = True
                self.buy_setup = False
                self.entry_trigger = float(self.data.low[-1])
                return
            self.sell_setup = True
            self.buy_setup = False
            self.entry_trigger = float(self.data.low[-1])

        if self.position:
            return

        if self.buy_setup and self.entry_trigger is not None and float(self.data.high[0]) > float(self.entry_trigger):
            self.signal_count += 1
            self.order = self.buy(size=float(self.p.lots))
            self.buy_setup = False
            return
        if self.sell_setup and self.entry_trigger is not None and float(self.data.low[0]) < float(self.entry_trigger):
            self.signal_count += 1
            self.order = self.sell(size=float(self.p.lots))
            self.sell_setup = False

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
