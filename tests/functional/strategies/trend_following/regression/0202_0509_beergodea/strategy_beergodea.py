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


class BeerGodEAStrategy(bt.Strategy):
    params = dict(
        lots=1.0,
        time_bar_open=3,
        period_ma=60,
    )

    def __init__(self):
        self.ema = bt.ind.ExponentialMovingAverage(self.data.close, period=int(self.p.period_ma))
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
        self.current_bar_start = None

    def next(self):
        self.bar_num += 1
        if len(self) < int(self.p.period_ma) + 2 or self.order is not None:
            return
        dt = bt.num2date(self.data.datetime[0])
        bar_start = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
        minutes_from_opening = int((dt - bar_start).total_seconds() // 60)
        if minutes_from_opening != int(self.p.time_bar_open):
            return
        ma_current = float(self.ema[0])
        ma_previous = float(self.ema[-1])
        close_1 = float(self.data.close[-1])
        bid = float(self.data.close[0])
        new_buy = bid < ma_current < ma_previous and bid < close_1
        new_sell = bid > ma_current > ma_previous and bid > close_1
        if new_buy and self.position.size <= 0:
            if self.position.size < 0:
                self.order = self.close()
            else:
                self.signal_count += 1
                self.order = self.buy(size=float(self.p.lots))
            return
        if new_sell and self.position.size >= 0:
            if self.position.size > 0:
                self.order = self.close()
            else:
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
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            if self.position.size == 0:
                self.order = None
            elif order.isbuy() and self.position.size < 0:
                self.order = self.buy(size=float(self.p.lots))
                self.signal_count += 1
                return
            elif order.issell() and self.position.size > 0:
                self.order = self.sell(size=float(self.p.lots))
                self.signal_count += 1
                return
            else:
                self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
