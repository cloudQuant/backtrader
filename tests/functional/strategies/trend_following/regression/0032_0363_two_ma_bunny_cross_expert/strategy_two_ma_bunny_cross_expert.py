from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class TwoMaBunnyCrossExpertStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        fast_ma_period=5,
        fast_ma_shift=0,
        slow_ma_period=20,
        slow_ma_shift=3,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.weighted_price = (self.data0_feed.high + self.data0_feed.low + (self.data0_feed.close * 2.0)) / 4.0
        self.fast_ma = bt.indicators.SimpleMovingAverage(self.weighted_price, period=self.p.fast_ma_period)
        self.slow_ma = bt.indicators.SimpleMovingAverage(self.weighted_price, period=self.p.slow_ma_period)
        self.entry_order = None
        self.close_order = None
        self.pending_side = None
        self.active_side = None
        self.entry_price = None
        self.buy_count = 0
        self.sell_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _minimum_bars(self):
        return max(self.p.fast_ma_period + self.p.fast_ma_shift + 2, self.p.slow_ma_period + self.p.slow_ma_shift + 2)

    def _bar_value(self, line, ago):
        return float(line[-ago]) if ago > 0 else float(line[0])

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _submit_entry(self, side, reason):
        if self.entry_order is not None or self.close_order is not None:
            self.pending_side = side
            return
        if self.position.size > 0 and side == 'long':
            return
        if self.position.size < 0 and side == 'short':
            return
        if self.position:
            self.pending_side = side
            self._submit_close(f'reverse to {side}: {reason}')
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.pending_side = None
        if side == 'long':
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN LONG size={size} reason={reason}')
        else:
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SHORT size={size} reason={reason}')

    def next(self):
        if len(self.data0_feed) < self._minimum_bars():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        fast_prev = self._bar_value(self.fast_ma, self.p.fast_ma_shift + 1)
        fast_now = self._bar_value(self.fast_ma, self.p.fast_ma_shift)
        slow_prev = self._bar_value(self.slow_ma, self.p.slow_ma_shift + 1)
        slow_now = self._bar_value(self.slow_ma, self.p.slow_ma_shift)
        signal_buy = fast_prev < slow_prev and fast_now > slow_now
        signal_sell = fast_prev > slow_prev and fast_now < slow_now
        if signal_buy:
            self._submit_entry('long', '5 SMA crossed above shifted 20 SMA')
        elif signal_sell:
            self._submit_entry('short', '5 SMA crossed below shifted 20 SMA')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_price = order.executed.price
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                if self.pending_side is not None:
                    next_side = self.pending_side
                    self.pending_side = None
                    self._submit_entry(next_side, 'post-close reversal')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.entry_price = None
