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


class ModifiedMovingAveragesStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        moving_period=12,
        moving_shift=6,
        stoploss_pips=105,
        takeprofit_pips=285,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.ma = bt.indicators.SimpleMovingAverage(self.data0_feed.close, period=self.p.moving_period)
        self.entry_order = None
        self.close_order = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None
        self.buy_count = 0
        self.sell_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _ma_value(self):
        return float(self.ma[-self.p.moving_shift]) if self.p.moving_shift > 0 else float(self.ma[0])

    def _initialize_exit_levels(self):
        if self.entry_price is None or self.active_side is None:
            return
        if self.active_side == 'long':
            self.stop_price = None if self.p.stoploss_pips <= 0 else self.entry_price - self.p.stoploss_pips * self.p.point_size
            self.limit_price = None if self.p.takeprofit_pips <= 0 else self.entry_price + self.p.takeprofit_pips * self.p.point_size
        else:
            self.stop_price = None if self.p.stoploss_pips <= 0 else self.entry_price + self.p.stoploss_pips * self.p.point_size
            self.limit_price = None if self.p.takeprofit_pips <= 0 else self.entry_price - self.p.takeprofit_pips * self.p.point_size

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _submit_entry(self, side, reason):
        if self.entry_order is not None or self.close_order is not None or self.position:
            return
        size = max(0.01, float(self.p.fixed_lot))
        if side == 'long':
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN LONG size={size} reason={reason}')
        else:
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SHORT size={size} reason={reason}')
        self.active_side = side

    def _check_exit_thresholds(self):
        if not self.position or self.close_order is not None:
            return False
        bar_high = float(self.data0_feed.high[0])
        bar_low = float(self.data0_feed.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and bar_low <= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_high >= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        else:
            if self.stop_price is not None and bar_high >= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_low <= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        return False

    def next(self):
        if len(self.data0_feed) < self.p.moving_period + self.p.moving_shift + 2:
            return
        if self._check_exit_thresholds():
            return
        ma_value = self._ma_value()
        bar_open = float(self.data0_feed.open[0])
        bar_close = float(self.data0_feed.close[0])
        open_long = bar_open < ma_value and bar_close > ma_value
        open_short = bar_open > ma_value and bar_close < ma_value
        if self.entry_order is not None or self.close_order is not None:
            return
        if self.position:
            if self.position.size > 0 and open_short:
                self._submit_close('bar crossed below MA')
            elif self.position.size < 0 and open_long:
                self._submit_close('bar crossed above MA')
            return
        if open_short:
            self._submit_entry('short', 'bar crossed below shifted SMA')
        elif open_long:
            self._submit_entry('long', 'bar crossed above shifted SMA')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_price = order.executed.price
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
                self._initialize_exit_levels()
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self._reset_exit_levels()
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
            self._reset_exit_levels()
