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


class WeightedPrice(bt.Indicator):
    lines = ('value',)

    def next(self):
        self.lines.value[0] = (float(self.data.high[0]) + float(self.data.low[0]) + 2.0 * float(self.data.close[0])) / 4.0


class MedianPrice(bt.Indicator):
    lines = ('value',)

    def next(self):
        self.lines.value[0] = (float(self.data.high[0]) + float(self.data.low[0])) / 2.0


class MaDeltaStrategy(bt.Strategy):
    params = dict(
        delta=195,
        multiplier=392,
        fast_period=26,
        slow_period=51,
        lot_divisor=2000.0,
        max_lot=15.0,
    )

    def __init__(self):
        self.fast_source = WeightedPrice(self.data)
        self.slow_source = MedianPrice(self.data)
        self.fast_ma = bt.indicators.SimpleMovingAverage(self.fast_source.value, period=self.p.fast_period)
        self.slow_ma = bt.indicators.ExponentialMovingAverage(self.slow_source.value, period=self.p.slow_period)

        self.order = None
        self.pending_reentry = 0
        self.pending_reentry_px = 0.0
        self.hi = 0.0
        self.lo = 0.0
        self.trade_signal = 0
        self.initialized = False
        self.previous_position_size = 0.0

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.d = float(self.p.delta) * 0.00001
        self.m = float(self.p.multiplier) * 0.1
        self.addminperiod(max(self.p.fast_period, self.p.slow_period) + 2)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _target_lot(self):
        free_cash = max(float(self.broker.getcash()), 0.0)
        lot = min(float(self.p.max_lot), round(free_cash / float(self.p.lot_divisor), 1))
        return lot if lot >= 0.1 else 0.0

    def _submit_entry(self, direction, px, count_signal=True):
        size = self._target_lot()
        if size <= 0.0:
            self.log(f'skip signal insufficient_free_cash cash={self.broker.getcash():.2f} direction={direction}')
            self.pending_reentry = 0
            self.pending_reentry_px = 0.0
            return False
        if count_signal:
            self.signal_count += 1
        if direction > 0:
            if count_signal:
                self.buy_count += 1
            self.log(f'buy signal px={px:.6f} target={size:.2f}')
            self.order = self.buy(size=size)
        else:
            if count_signal:
                self.sell_count += 1
            self.log(f'sell signal px={px:.6f} target={size:.2f}')
            self.order = self.sell(size=size)
        return True

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        px = pow(self.m * (float(self.fast_ma[0]) - float(self.slow_ma[0])), 3)
        if not self.initialized:
            self.hi = 0.0
            self.lo = 0.0
            self.trade_signal = 0
            self.initialized = True
        if px > self.hi:
            self.hi = px
            self.lo = self.hi - self.d
            self.trade_signal = 1
        if px < self.lo:
            self.lo = px
            self.hi = self.lo + self.d
            self.trade_signal = -1

        current_size = float(self.position.size)
        if self.pending_reentry != 0 and current_size == 0.0:
            direction = self.pending_reentry
            px_to_use = self.pending_reentry_px
            self.pending_reentry = 0
            self.pending_reentry_px = 0.0
            self._submit_entry(direction, px_to_use, count_signal=False)
            return

        if self.trade_signal == 1 and current_size < 0.0:
            self.signal_count += 1
            self.buy_count += 1
            self.pending_reentry = 1
            self.pending_reentry_px = px
            self.log(f'buy/reverse signal px={px:.6f} current={current_size:.2f}')
            self.order = self.close()
            return

        if self.trade_signal == -1 and current_size > 0.0:
            self.signal_count += 1
            self.sell_count += 1
            self.pending_reentry = -1
            self.pending_reentry_px = px
            self.log(f'sell/reverse signal px={px:.6f} current={current_size:.2f}')
            self.order = self.close()
            return

        if current_size != 0.0:
            return
        if self.trade_signal == 1:
            self._submit_entry(1, px, count_signal=True)
        elif self.trade_signal == -1:
            self._submit_entry(-1, px, count_signal=True)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            self.order = None
            if self.pending_reentry != 0 and not self.position:
                direction = self.pending_reentry
                px = self.pending_reentry_px
                self.pending_reentry = 0
                self.pending_reentry_px = 0.0
                self._submit_entry(direction, px, count_signal=False)
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            self.pending_reentry = 0
            self.pending_reentry_px = 0.0
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        pnl = float(trade.pnlcomm)
        self.trade_count += 1
        if pnl >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={pnl:.2f}')
