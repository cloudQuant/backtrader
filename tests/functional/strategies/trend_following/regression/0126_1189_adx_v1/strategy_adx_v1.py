from __future__ import absolute_import, division, print_function, unicode_literals

import io
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


class AdxV1Strategy(bt.Strategy):
    params = dict(
        lots=0.1,
        stop_loss_points=500,
        take_profit_points=500,
        point=0.01,
        shift=1,
        adx_period=28,
        level_p=5,
        level_m=5,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.plus_di = bt.indicators.PlusDirectionalIndicator(self.base, period=self.p.adx_period)
        self.minus_di = bt.indicators.MinusDirectionalIndicator(self.base, period=self.p.adx_period)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.entry_price = None
        self.stop_price = None
        self.take_price = None
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _cross_signal(self):
        shift = int(self.p.shift)
        p0 = float(self.plus_di[-shift])
        p1 = float(self.plus_di[-(shift + 1)])
        m0 = float(self.minus_di[-shift])
        m1 = float(self.minus_di[-(shift + 1)])
        if p0 > float(self.p.level_p) and p1 < float(self.p.level_p):
            return 1, p0, m0
        if m0 > float(self.p.level_m) and m1 < float(self.p.level_m):
            return -1, p0, m0
        return 0, p0, m0

    def _set_levels(self, is_long, price):
        stop_distance = float(self.p.stop_loss_points) * float(self.p.point)
        take_distance = float(self.p.take_profit_points) * float(self.p.point)
        if is_long:
            self.stop_price = price - stop_distance
            self.take_price = price + take_distance
        else:
            self.stop_price = price + stop_distance
            self.take_price = price - take_distance

    def _check_exit_levels(self):
        if not self.position or self.entry_price is None:
            return False
        close_price = float(self.base.close[0])
        if self.position.size > 0:
            if close_price <= self.stop_price:
                self.log(f'close long by stop loss close={close_price:.2f} entry={self.entry_price:.2f}')
                self.close()
                return True
            if close_price >= self.take_price:
                self.log(f'close long by take profit close={close_price:.2f} entry={self.entry_price:.2f}')
                self.close()
                return True
        if self.position.size < 0:
            if close_price >= self.stop_price:
                self.log(f'close short by stop loss close={close_price:.2f} entry={self.entry_price:.2f}')
                self.close()
                return True
            if close_price <= self.take_price:
                self.log(f'close short by take profit close={close_price:.2f} entry={self.entry_price:.2f}')
                self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < self.p.adx_period + self.p.shift + 3:
            return
        if self.entry_order is not None:
            return
        if self._check_exit_levels():
            return
        if self.position:
            return

        signal, plus_di, minus_di = self._cross_signal()
        if signal == 0:
            if plus_di > minus_di and plus_di > float(self.p.level_p):
                signal = 1
            elif minus_di > plus_di and minus_di > float(self.p.level_m):
                signal = -1
        if signal > 0:
            self.signal_count += 1
            close_price = float(self.base.close[0])
            self.log(f'buy signal close={close_price:.2f} plus_di={plus_di:.2f} minus_di={minus_di:.2f}')
            self._set_levels(True, close_price)
            self.entry_order = self.buy(size=abs(float(self.p.lots)))
            return
        if signal < 0:
            self.signal_count += 1
            close_price = float(self.base.close[0])
            self.log(f'sell signal close={close_price:.2f} plus_di={plus_di:.2f} minus_di={minus_di:.2f}')
            self._set_levels(False, close_price)
            self.entry_order = self.sell(size=abs(float(self.p.lots)))

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                self.entry_price = float(order.executed.price)
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.entry_price = None
                self.stop_price = None
                self.take_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
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
