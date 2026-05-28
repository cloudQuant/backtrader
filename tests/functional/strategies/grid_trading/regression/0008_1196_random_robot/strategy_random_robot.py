from __future__ import absolute_import, division, print_function, unicode_literals

import io
import random
import sys
import time
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_SRC = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_SRC) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_SRC))

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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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


class RandomRobotStrategy(bt.Strategy):
    params = dict(
        profit_target=1000,
        stop_loss=3000,
        lot=0.1,
        really_random=False,
        seed=1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self.order = None
        self.entry_price = None
        self.stop_price = None
        self.take_price = None
        self.last_coin_toss = None
        seed = int(time.time()) if self.p.really_random else int(self.p.seed)
        self.rng = random.Random(seed)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _close_for_levels(self):
        if not self.position:
            return False
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long take={self.take_price:.2f}')
                self.order = self.close()
                return True
            return False
        if self.stop_price is not None and high >= self.stop_price:
            self.log(f'close short stop={self.stop_price:.2f}')
            self.order = self.close()
            return True
        if self.take_price is not None and low <= self.take_price:
            self.log(f'close short take={self.take_price:.2f}')
            self.order = self.close()
            return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < 2:
            return
        if self.order:
            return
        if self._close_for_levels():
            return
        if self.position:
            return

        self.last_coin_toss = self.rng.randint(0, 1)
        if self.last_coin_toss == 0:
            self.log('coin toss=0 buy')
            self.order = self.buy(size=self.p.lot)
            return
        self.log('coin toss=1 sell')
        self.order = self.sell(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.position:
                self.entry_price = float(order.executed.price)
                if self.position.size > 0:
                    self.stop_price = round(self.entry_price - self.p.stop_loss * self.p.point, self.p.price_digits)
                    self.take_price = round(self.entry_price + self.p.profit_target * self.p.point, self.p.price_digits)
                    self.log(f'long filled price={self.entry_price:.2f} size={abs(self.position.size):.2f} stop={self.stop_price:.2f} take={self.take_price:.2f}')
                else:
                    self.stop_price = round(self.entry_price + self.p.stop_loss * self.p.point, self.p.price_digits)
                    self.take_price = round(self.entry_price - self.p.profit_target * self.p.point, self.p.price_digits)
                    self.log(f'short filled price={self.entry_price:.2f} size={abs(self.position.size):.2f} stop={self.stop_price:.2f} take={self.take_price:.2f}')
            else:
                self.entry_price = None
                self.stop_price = None
                self.take_price = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order {order.getstatusname()}')
            if not self.position:
                self.entry_price = None
                self.stop_price = None
                self.take_price = None
        self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
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
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
