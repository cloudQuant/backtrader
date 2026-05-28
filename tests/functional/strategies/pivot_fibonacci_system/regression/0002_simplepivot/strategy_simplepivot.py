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


def resample_daily(df):
    daily = df.resample('1D', label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
        'spread': 'last',
    }).dropna()
    return daily


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


class SimplePivotStrategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.entry_order = None
        self.close_order = None
        self.pending_side = None
        self.last_trade_side = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signal_side(self):
        pivot = (float(self.data0_feed.high[-1]) + float(self.data0_feed.low[-1])) / 2.0
        current_open = float(self.data0_feed.open[0])
        previous_high = float(self.data0_feed.high[-1])
        if current_open < previous_high and current_open > pivot:
            return 'short'
        return 'long'

    def _submit_entry(self, side):
        size = max(0.01, float(self.p.fixed_lot))
        if side == 'long':
            self.entry_order = self.buy(size=size)
        else:
            self.entry_order = self.sell(size=size)
        self.pending_side = side
        self.log(f'OPEN {side.upper()} signal open={float(self.data0_feed.open[0]):.5f}')

    def next(self):
        if len(self.data0_feed) < 2:
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        desired_side = self._signal_side()
        if self.last_trade_side is not None and desired_side == self.last_trade_side:
            return
        if self.position:
            self.pending_side = desired_side
            self.close_order = self.close()
            self.log(f'CLOSE current position for flip to {desired_side.upper()}')
            return
        self._submit_entry(desired_side)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                if not self.position and self.pending_side is not None:
                    next_side = self.pending_side
                    self.pending_side = None
                    self._submit_entry(next_side)
                return
            if order == self.entry_order:
                self.last_trade_side = self.pending_side
                self.log(f'ENTRY FILLED side={self.last_trade_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
                self.pending_side = None
                return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.close_order:
                self.close_order = None
            if order == self.entry_order:
                self.entry_order = None
                self.pending_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        side = self.last_trade_side or ('long' if trade.long else 'short')
        self.log(f'TRADE CLOSED side={side} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
