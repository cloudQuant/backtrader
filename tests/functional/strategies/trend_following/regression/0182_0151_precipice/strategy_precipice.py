from __future__ import absolute_import, division, print_function, unicode_literals

import io
import random
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class PrecipiceStrategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        point_size=0.01,
        sltp_pips=100,
        use_buy=True,
        use_sell=True,
        random_seed=151,
    )

    def __init__(self):
        self.rng = random.Random(int(self.p.random_seed))
        self.last_bar_dt = None
        self.stop_order = None
        self.limit_order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.datas[0].datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_bar(self):
        current = bt.num2date(self.datas[0].datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _cancel_exits(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _place_exits(self):
        if not self.position:
            return
        distance = self.p.sltp_pips * self.p.point_size
        size = abs(self.position.size)
        if self.position.size > 0:
            self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.position.price - distance)
            self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=self.position.price + distance, oco=self.stop_order)
        else:
            self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.position.price + distance)
            self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=self.position.price - distance, oco=self.stop_order)

    def next(self):
        self.bar_num += 1
        if not self._new_bar():
            return
        if self.position:
            return
        size = max(0.01, float(self.p.fixed_lot))
        roll = self.rng.random()
        if self.p.use_buy and roll < 0.5:
            self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN LONG size={size} roll={roll:.5f}')
            return
        if self.p.use_sell and roll >= 0.5:
            self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SHORT size={size} roll={roll:.5f}')
            return
        if self.p.use_buy and not self.p.use_sell:
            self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN LONG size={size} roll={roll:.5f} forced=buy_only')
        elif self.p.use_sell and not self.p.use_buy:
            self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SHORT size={size} roll={roll:.5f} forced=sell_only')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and self.position.size > 0:
                self.log(f'ENTRY FILLED side=long price={order.executed.price:.5f} size={order.executed.size}')
                self._place_exits()
            elif order.issell() and self.position.size < 0:
                self.log(f'ENTRY FILLED side=short price={order.executed.price:.5f} size={order.executed.size}')
                self._place_exits()
            elif order == self.stop_order:
                self.stop_order = None
                self.limit_order = None
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
            elif order == self.limit_order:
                self.limit_order = None
                self.stop_order = None
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._cancel_exits()
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
