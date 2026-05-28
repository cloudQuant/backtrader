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
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime')
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


class SimplePriceStrategy(bt.Strategy):
    params = dict(
        check_bars=60,
        lots=0.1,
        point=0.01,
        price_digits=2,
        tp_points=50,
    )

    def __init__(self):
        self.move_up = None
        self.move_down = None
        self.entry_order = None
        self.tp_order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_price(self, value):
        return round(value, self.p.price_digits)

    def _calc_levels(self):
        lows = [float(self.data.low[-i]) for i in range(self.p.check_bars)]
        highs = [float(self.data.high[-i]) for i in range(self.p.check_bars)]
        self.move_up = min(lows)
        self.move_down = max(highs)

    def _cancel_tp(self):
        if self.tp_order is not None and self.tp_order.alive():
            self.cancel(self.tp_order)
        self.tp_order = None

    def _ensure_tp(self):
        if not self.position or self.tp_order is not None:
            return
        spread_points = float(self.data.spread[0])
        tp_distance = (self.p.tp_points + spread_points) * self.p.point
        if self.position.size > 0:
            tp_price = self._round_price(self.position.price + tp_distance)
            self.tp_order = self.sell(size=abs(self.position.size), exectype=bt.Order.Limit, price=tp_price)
        else:
            tp_price = self._round_price(self.position.price - tp_distance)
            self.tp_order = self.buy(size=abs(self.position.size), exectype=bt.Order.Limit, price=tp_price)
        self.log(f'apply take-profit tp={tp_price:.2f}')

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.check_bars:
            return
        self._calc_levels()
        if self.position:
            self._ensure_tp()
            return
        if self.entry_order is not None:
            return
        current_low = float(self.data.low[0])
        current_high = float(self.data.high[0])
        current_close = float(self.data.close[0])
        if current_low <= self.move_up:
            self.entry_order = self.buy(size=self.p.lots)
            self.log(f'buy signal support={self.move_up:.2f} close={current_close:.2f}')
            return
        if current_high >= self.move_down:
            self.entry_order = self.sell(size=self.p.lots)
            self.log(f'sell signal resistance={self.move_down:.2f} close={current_close:.2f}')

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order is self.entry_order:
            if order.status == order.Completed:
                if order.isbuy():
                    self.buy_count += 1
                    self.log(f'buy filled price={order.executed.price:.2f}')
                else:
                    self.sell_count += 1
                    self.log(f'sell filled price={order.executed.price:.2f}')
                self.entry_order = None
            else:
                self.entry_order = None
            return
        if order is self.tp_order:
            if order.status == order.Completed:
                self.log(f'take-profit filled price={order.executed.price:.2f}')
                self.tp_order = None
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.tp_order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
                self.log(f'buy filled price={trade.price:.2f}')
            elif trade.size < 0:
                self.sell_count += 1
                self.log(f'sell filled price={trade.price:.2f}')
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
        self._cancel_tp()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
