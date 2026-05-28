from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class InverseReactionIndicator(bt.Indicator):
    lines = ('price_change', 'upper_level', 'lower_level')
    params = dict(ma_period=3, coefficient=1.618)

    def __init__(self):
        self.addminperiod(self.p.ma_period)

    def next(self):
        price_change = float(self.data.close[0] - self.data.open[0])
        self.lines.price_change[0] = price_change
        if len(self) < self.p.ma_period:
            self.lines.upper_level[0] = float('nan')
            self.lines.lower_level[0] = float('nan')
            return
        total = 0.0
        for i in range(self.p.ma_period):
            total += abs(float(self.data.close[-i] - self.data.open[-i]))
        dcl = (total / float(self.p.ma_period)) * float(self.p.coefficient)
        self.lines.upper_level[0] = dcl
        self.lines.lower_level[0] = -dcl


class IreaStrategy(bt.Strategy):
    params = dict(
        stop_loss=1000,
        take_profit=250,
        trade_volume=1.0,
        slippage=3,
        min_criteria=300,
        max_criteria=2000,
        coefficient=1.618,
        ma_period=3,
        point=0.01,
    )

    def __init__(self):
        self.ir = InverseReactionIndicator(
            self.data,
            ma_period=self.p.ma_period,
            coefficient=self.p.coefficient,
        )
        self.order = None
        self.pending_entry = None
        self.stop_price = None
        self.take_price = None

        self.min_criteria_price = float(self.p.min_criteria) * float(self.p.point)
        self.max_criteria_price = float(self.p.max_criteria) * float(self.p.point)
        self.stop_loss_price = float(self.p.stop_loss) * float(self.p.point)
        self.take_profit_price = float(self.p.take_profit) * float(self.p.point)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.addminperiod(max(self.p.ma_period, 3))

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signal_at(self, ago):
        price_change = float(self.ir.price_change[ago])
        upper_level = float(self.ir.upper_level[ago])
        if not math.isfinite(price_change) or not math.isfinite(upper_level):
            return False
        change = abs(price_change)
        return change > upper_level and change < self.max_criteria_price and change > self.min_criteria_price

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self.position:
            self._check_exit_levels()
            return
        current_signal = self._signal_at(0)
        previous_signal = self._signal_at(-1) if len(self) > 1 else False
        if not current_signal or previous_signal:
            return
        self.signal_count += 1
        size = max(float(self.p.trade_volume), 0.01)
        price_change = float(self.ir.price_change[0])
        if price_change < 0:
            self.buy_count += 1
            self.pending_entry = 'long'
            self.log(f'buy signal price_change={price_change:.5f}')
            self.order = self.buy(size=size)
        else:
            self.sell_count += 1
            self.pending_entry = 'short'
            self.log(f'sell signal price_change={price_change:.5f}')
            self.order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed and self.pending_entry is not None:
            entry_price = float(order.executed.price)
            if self.pending_entry == 'long':
                self.stop_price = entry_price - self.stop_loss_price
                self.take_price = entry_price + self.take_profit_price
            else:
                self.stop_price = entry_price + self.stop_loss_price
                self.take_price = entry_price - self.take_profit_price
            self.log(f'entry filled side={self.pending_entry} price={entry_price:.5f}')
            self.pending_entry = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            self.pending_entry = None
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.stop_price = None
        self.take_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
