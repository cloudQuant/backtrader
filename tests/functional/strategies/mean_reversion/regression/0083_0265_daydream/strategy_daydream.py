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


class DaydreamStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        virtual_takeprofit_pips=50,
        channel_bars=25,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.entry_order = None
        self.close_order = None
        self.pending_reverse = None
        self.active_side = None
        self.entry_price = None
        self.last_bar_dt = None
        self.last_entry_dt = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def prenext(self):
        self.next()

    def _new_bar(self):
        current = bt.num2date(self.data0_feed.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        if side == 'long':
            self.entry_order = self.buy(size=size)
        else:
            self.entry_order = self.sell(size=size)
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse}')

    def _check_virtual_takeprofit(self):
        if not self.position or self.entry_price is None or self.close_order is not None:
            return False
        distance = self.p.virtual_takeprofit_pips * self.p.point_size
        current_price = float(self.data0_feed.close[0])
        if self.position.size > 0 and current_price - self.entry_price > distance:
            self._submit_close('virtual take profit hit', reverse=None)
            return True
        if self.position.size < 0 and self.entry_price - current_price > distance:
            self._submit_close('virtual take profit hit', reverse=None)
            return True
        return False

    def next(self):
        if len(self.data0_feed) < self.p.channel_bars + 3:
            return
        if self._check_virtual_takeprofit():
            return
        if not self.position and self.pending_reverse and self.entry_order is None and self.close_order is None:
            side = self.pending_reverse
            self.pending_reverse = None
            self._submit_entry(side, 'reverse after close')
            return
        if not self._new_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        highest_value = max(float(self.data0_feed.high[-i]) for i in range(1, self.p.channel_bars + 1))
        lowest_value = min(float(self.data0_feed.low[-i]) for i in range(1, self.p.channel_bars + 1))
        close_0 = float(self.data0_feed.close[0])
        time_0 = bt.num2date(self.data0_feed.datetime[0])
        if close_0 < lowest_value and self.last_entry_dt != time_0:
            if self.position.size < 0:
                self._submit_close('reverse to long breakout', reverse='long')
            elif not self.position:
                self._submit_entry('long', 'close below channel low')
            return
        if close_0 > highest_value and self.last_entry_dt != time_0:
            if self.position.size > 0:
                self._submit_close('reverse to short breakout', reverse='short')
            elif not self.position:
                self._submit_entry('short', 'close above channel high')
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_price = order.executed.price
                self.last_entry_dt = bt.num2date(self.data0_feed.datetime[0])
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                reverse = self.pending_reverse
                self.pending_reverse = None
                self.active_side = None
                self.entry_price = None
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, 'reverse after close')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                self.pending_reverse = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.entry_price = None
