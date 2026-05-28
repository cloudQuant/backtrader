from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
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


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class Twenty200PipsStrategy(bt.Strategy):
    params = dict(
        take_profit_points=200,
        stop_loss_points=2000,
        trade_time_hour=18,
        t1=7,
        t2=2,
        delta_points=70,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.h1 = self.datas[1]
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self._position_was_open = False
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _clear_exit_levels(self):
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.log(f'close long tp={self.take_profit_price:.2f}')
                self.order = self.close()
                return True
        elif self.position.size < 0:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.log(f'close short tp={self.take_profit_price:.2f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if len(self.h1) <= max(int(self.p.t1), int(self.p.t2)):
            return
        if self._manage_risk():
            return
        if self.position:
            return

        signal_dt = bt.num2date(self.h1.datetime[0])
        if signal_dt.hour != int(self.p.trade_time_hour):
            return
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        open_t1 = float(self.h1.open[-int(self.p.t1)])
        open_t2 = float(self.h1.open[-int(self.p.t2)])
        delta_price = float(self.p.delta_points) * float(self.p.point)
        size = abs(float(self.p.lot))
        if size <= 0:
            return

        if open_t1 > open_t2 + delta_price:
            self.signal_count += 1
            self.entry_side = 'short'
            self.log(f'sell signal h1_open_t1={open_t1:.2f} h1_open_t2={open_t2:.2f}')
            self.order = self.sell(size=size)
            return
        if open_t1 + delta_price < open_t2:
            self.signal_count += 1
            self.entry_side = 'long'
            self.log(f'buy signal h1_open_t1={open_t1:.2f} h1_open_t2={open_t2:.2f}')
            self.order = self.buy(size=size)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            self.completed_order_count += 1
            if order.isbuy() and self.entry_side == 'long' and self.position.size > 0:
                price = float(order.executed.price)
                self.stop_price = round(price - float(self.p.stop_loss_points) * float(self.p.point), int(self.p.price_digits))
                self.take_profit_price = round(price + float(self.p.take_profit_points) * float(self.p.point), int(self.p.price_digits))
                self.log(f'long filled price={price:.2f} sl={self.stop_price:.2f} tp={self.take_profit_price:.2f}')
            elif order.issell() and self.entry_side == 'short' and self.position.size < 0:
                price = float(order.executed.price)
                self.stop_price = round(price + float(self.p.stop_loss_points) * float(self.p.point), int(self.p.price_digits))
                self.take_profit_price = round(price - float(self.p.take_profit_points) * float(self.p.point), int(self.p.price_digits))
                self.log(f'short filled price={price:.2f} sl={self.stop_price:.2f} tp={self.take_profit_price:.2f}')
            elif not self.position:
                self._clear_exit_levels()
        elif order.status in [order.Canceled, order.Margin, order.Rejected, order.Expired]:
            self.rejected_order_count += 1
            if not self.position:
                self._clear_exit_levels()
            self.log(f'order {order.getstatusname()}')
        if self.order is not None and order.ref == self.order.ref and order.status not in [order.Submitted, order.Accepted]:
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
        self._clear_exit_levels()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
