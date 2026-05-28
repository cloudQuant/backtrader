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


class ZigZagRecentPivotSignal(bt.Indicator):
    lines = ('signal', 'pivot_age', 'pivot_price')
    params = dict(depth=17, deviation=7, backstep=5, point=0.01)

    def __init__(self):
        self.addminperiod(self.p.depth + self.p.backstep + 2)
        self._last_pivot_type = 0
        self._last_pivot_price = None
        self._latest_signal = 0
        self._latest_age = 999999
        self._latest_pivot_price = 0.0

    def next(self):
        self.lines.signal[0] = 0
        self.lines.pivot_age[0] = self._latest_age if self._latest_age < 999999 else 999999
        self.lines.pivot_price[0] = self._latest_pivot_price

        if len(self.data) <= self.p.depth + self.p.backstep:
            return

        shift = self.p.backstep
        candidate_high = float(self.data.high[-shift])
        candidate_low = float(self.data.low[-shift])
        high_window = [float(self.data.high[-shift - i]) for i in range(self.p.depth)]
        low_window = [float(self.data.low[-shift - i]) for i in range(self.p.depth)]
        deviation_abs = self.p.deviation * self.p.point

        pivot_type = 0
        pivot_price = None
        if candidate_high >= max(high_window):
            pivot_type = 1
            pivot_price = candidate_high
        elif candidate_low <= min(low_window):
            pivot_type = -1
            pivot_price = candidate_low

        if pivot_type != 0 and pivot_price is not None:
            is_new_pivot = False
            if self._last_pivot_price is None:
                is_new_pivot = True
            elif pivot_type != self._last_pivot_type and abs(pivot_price - self._last_pivot_price) >= deviation_abs:
                is_new_pivot = True
            elif pivot_type == self._last_pivot_type:
                if pivot_type == 1 and pivot_price > self._last_pivot_price:
                    is_new_pivot = True
                if pivot_type == -1 and pivot_price < self._last_pivot_price:
                    is_new_pivot = True
            if is_new_pivot:
                self._last_pivot_type = pivot_type
                self._last_pivot_price = pivot_price
                self._latest_signal = 1 if pivot_type == 1 else -1
                self._latest_age = 0
                self._latest_pivot_price = pivot_price

        if self._latest_age < 999999:
            self.lines.signal[0] = self._latest_signal
            self.lines.pivot_age[0] = self._latest_age
            self.lines.pivot_price[0] = self._latest_pivot_price
            self._latest_age += 1


class ZigZagEvgeTrofiVer1Strategy(bt.Strategy):
    params = dict(
        depth=17,
        deviation=7,
        backstep=5,
        lot=0.10,
        signal_reverse=False,
        urgency=2,
        point=0.01,
    )

    def __init__(self):
        self.signal_indicator = ZigZagRecentPivotSignal(
            self.data,
            depth=self.p.depth,
            deviation=self.p.deviation,
            backstep=self.p.backstep,
            point=self.p.point,
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
        if len(self.data) <= self.p.depth + self.p.backstep + 2:
            return
        if self.order:
            return

        raw_signal = int(self.signal_indicator.signal[0])
        pivot_age = int(self.signal_indicator.pivot_age[0]) if self.signal_indicator.pivot_age[0] < 999999 else 999999
        signal = raw_signal
        if self.p.signal_reverse:
            signal = -signal
        if signal == 0 or pivot_age > self.p.urgency:
            return

        if signal == 1 and self.position.size < 0:
            self.order = self.close()
            return
        if signal == -1 and self.position.size > 0:
            self.order = self.close()
            return

        if signal == 1:
            self.order = self.buy(size=self.p.lot)
        elif signal == -1:
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
