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


class Russian20HP1Strategy(bt.Strategy):
    params = dict(
        fixed_lot=0.01,
        point_size=0.01,
        stoploss_buy_pips=50,
        takeprofit_buy_pips=50,
        stoploss_sell_pips=50,
        takeprofit_sell_pips=50,
        every_tick=False,
        ma_period=20,
        momentum_period=5,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.ma = bt.indicators.SimpleMovingAverage(self.data0_feed.close, period=self.p.ma_period)
        self.momentum = bt.indicators.Momentum(self.data0_feed.close, period=self.p.momentum_period)
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.active_side = None
        self.last_bar_dt = None

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

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        price = float(self.data0_feed.close[0])
        if side == 'long':
            sl = price - self.p.stoploss_buy_pips * self.p.point_size if self.p.stoploss_buy_pips else price - 10e6
            tp = price + self.p.takeprofit_buy_pips * self.p.point_size if self.p.takeprofit_buy_pips else price + 10e6
            self.entry_order, self.stop_order, self.limit_order = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
            self.log(f'OPEN LONG size={size} reason={reason}')
        else:
            sl = price + self.p.stoploss_sell_pips * self.p.point_size if self.p.stoploss_sell_pips else price + 10e6
            tp = price - self.p.takeprofit_sell_pips * self.p.point_size if self.p.takeprofit_sell_pips else price - 10e6
            self.entry_order, self.stop_order, self.limit_order = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
            self.log(f'OPEN SHORT size={size} reason={reason}')

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse=None')

    def next(self):
        if len(self.data0_feed) < max(self.p.ma_period, self.p.momentum_period) + 2:
            return
        if not self.p.every_tick and not self._new_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        close0 = float(self.data0_feed.close[0])
        close1 = float(self.data0_feed.close[-1])
        ma0 = float(self.ma[0])
        mom0 = float(self.momentum[0])
        if not self.position:
            if close0 > ma0 and mom0 > 100.0 and close0 > close1:
                self._submit_entry('long', 'close>ma and momentum>100 and rising close')
                return
            if close0 < ma0 and mom0 < 100.0 and close0 < close1:
                self._submit_entry('short', 'close<ma and momentum<100 and falling close')
                return
        else:
            if self.position.size > 0 and mom0 < 100.0:
                self._submit_close('momentum below 100 for long')
            elif self.position.size < 0 and mom0 > 100.0:
                self._submit_close('momentum above 100 for short')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
