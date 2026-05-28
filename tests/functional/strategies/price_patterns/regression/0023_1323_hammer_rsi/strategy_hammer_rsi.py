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


class HammerRsiStrategy(bt.Strategy):
    params = dict(
        rsi_period=14,
        rsi_entry_long=40,
        rsi_entry_short=60,
        rsi_exit_upper=70,
        rsi_exit_lower=30,
        ma_period=5,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.close_avg = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def _is_hammer(self):
        o1, h1, l1, c1 = (float(self.data.open[-1]), float(self.data.high[-1]), float(self.data.low[-1]), float(self.data.close[-1]))
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        mid1 = (o1 + c1) / 2.0
        avg2 = float(self.close_avg[-2])
        rng = h1 - l1
        if rng < self.p.point:
            return False
        body_low = min(o1, c1)
        return mid1 < avg2 and body_low > (h1 - rng / 3.0) and c1 < c2 and o1 < o2

    def _is_hanging_man(self):
        o1, h1, l1, c1 = (float(self.data.open[-1]), float(self.data.high[-1]), float(self.data.low[-1]), float(self.data.close[-1]))
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        mid1 = (o1 + c1) / 2.0
        avg2 = float(self.close_avg[-2])
        rng = h1 - l1
        if rng < self.p.point:
            return False
        body_low = min(o1, c1)
        return mid1 > avg2 and body_low > (h1 - rng / 3.0) and c1 > c2 and o1 > o2

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.rsi_period, self.p.ma_period) + 5
        if len(self.data) < warmup:
            return
        rsi0 = float(self.rsi[0])
        rsi1 = float(self.rsi[-1])
        if self.position:
            if self.position.size > 0:
                if ((rsi0 > self.p.rsi_exit_lower and rsi1 < self.p.rsi_exit_lower) or
                    (rsi0 < self.p.rsi_exit_upper and rsi1 > self.p.rsi_exit_upper)):
                    self.close()
                    return
            elif self.position.size < 0:
                if ((rsi0 < self.p.rsi_exit_upper and rsi1 > self.p.rsi_exit_upper) or
                    (rsi0 > self.p.rsi_exit_lower and rsi1 < self.p.rsi_exit_lower)):
                    self.close()
                    return
        else:
            if self._is_hammer() and rsi0 < self.p.rsi_entry_long:
                self.buy(size=self.p.lot)
                return
            if self._is_hanging_man() and rsi0 > self.p.rsi_entry_short:
                self.sell(size=self.p.lot)
                return

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
