from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={'<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest'})
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5))


class MALWorldStrategy(bt.Strategy):
    params = dict(period_fast=12, period_slow=25, stop_loss_points=95.0, take_profit_points=670.0, trailing_ma_period=92, fixed_lot=0.1, point=0.01)

    def __init__(self):
        self.data0 = self.datas[0]
        self.fast_ma = bt.indicators.WeightedMovingAverage(self.data0.close, period=int(self.p.period_fast))
        self.slow_ma = bt.indicators.WeightedMovingAverage(self.data0.close, period=int(self.p.period_slow))
        self.trailing_ma = bt.indicators.ExponentialMovingAverage(self.data0.close, period=int(self.p.trailing_ma_period))
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        print(f'{bt.num2date(self.data0.datetime[0]).isoformat()}, {text}')

    def _check_exit_levels(self):
        if not self.position:
            return False
        cp = float(self.data0.close[0])
        sd = float(self.p.stop_loss_points) * float(self.p.point)
        td = float(self.p.take_profit_points) * float(self.p.point)
        ep = float(self.position.price)
        if self.position.size > 0:
            if cp <= ep - sd or cp >= ep + td or cp < float(self.trailing_ma[0]):
                self.close()
                return True
        else:
            if cp >= ep + sd or cp <= ep - td or cp > float(self.trailing_ma[0]):
                self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self._check_exit_levels():
            return
        cross = int(self.crossover[0])
        if cross > 0:
            if self.position.size < 0:
                self.close()
            if self.position.size <= 0:
                self.signal_count += 1
                self.log(f'buy signal {float(self.data0.close[0]):.2f}')
                self.buy(size=float(self.p.fixed_lot))
        elif cross < 0:
            if self.position.size > 0:
                self.close()
            if self.position.size >= 0:
                self.signal_count += 1
                self.log(f'sell signal {float(self.data0.close[0]):.2f}')
                self.sell(size=float(self.p.fixed_lot))

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
