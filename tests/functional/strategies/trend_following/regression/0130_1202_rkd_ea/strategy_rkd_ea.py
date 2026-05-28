from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
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


class RKDIndicator(bt.Indicator):
    lines = ('rsv', 'k', 'd')
    params = dict(kd_period=30, m1=3, m2=6)

    def __init__(self):
        self.addminperiod(max(int(self.p.kd_period), int(self.p.m1), int(self.p.m2)) + 2)

    def next(self):
        kd_period = int(self.p.kd_period)
        m1 = int(self.p.m1)
        m2 = int(self.p.m2)
        highs = [float(self.data.high[-i]) for i in range(kd_period)]
        lows = [float(self.data.low[-i]) for i in range(kd_period)]
        max_high = max(highs)
        min_low = min(lows)
        denom = max_high - min_low
        if denom == 0:
            rsv = 0.0
        else:
            rsv = (float(self.data.close[0]) - min_low) / denom * 100.0
        self.lines.rsv[0] = rsv

        if len(self) < m1:
            self.lines.k[0] = 0.0
        else:
            self.lines.k[0] = sum(float(self.lines.rsv[-i]) for i in range(m1)) / m1

        if len(self) < m2:
            self.lines.d[0] = 0.0
        else:
            self.lines.d[0] = sum(float(self.lines.k[-i]) for i in range(m2)) / m2


class RkdEaStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        stop_loss_points=31,
        take_profit_points=50,
        point=0.01,
        kd_period=30,
        m1=3,
        m2=6,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.rkd = RKDIndicator(self.base, kd_period=self.p.kd_period, m1=self.p.m1, m2=self.p.m2)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _stop_distance(self):
        return float(self.p.stop_loss_points) * float(self.p.point) if float(self.p.stop_loss_points) > 100 else None

    def _take_distance(self):
        return float(self.p.take_profit_points) * float(self.p.point) if float(self.p.take_profit_points) > 100 else None

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        stop_distance = self._stop_distance()
        take_distance = self._take_distance()
        entry_price = float(self.position.price)

        if self.position.size > 0:
            if stop_distance is not None and close_price <= entry_price - stop_distance:
                self.log(f'close long by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price >= entry_price + take_distance:
                self.log(f'close long by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        elif self.position.size < 0:
            if stop_distance is not None and close_price >= entry_price + stop_distance:
                self.log(f'close short by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price <= entry_price - take_distance:
                self.log(f'close short by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 4:
            return

        if self._check_exit_levels():
            return

        k1 = float(self.rkd.k[-1])
        d1 = float(self.rkd.d[-1])
        k2 = float(self.rkd.k[-2])
        d2 = float(self.rkd.d[-2])
        close_price = float(self.base.close[0])
        size = abs(float(self.p.lots))
        if size <= 0:
            return

        open_long = k1 > d1 and k2 < d2
        open_short = k1 < d1 and k2 > d2
        reverse_to_long = self.position.size < 0 and open_long
        reverse_to_short = self.position.size > 0 and open_short

        if open_long:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} k1={k1:.2f} d1={d1:.2f}')
            order_size = size if self.position.size >= 0 else abs(float(self.position.size)) + size
            self.buy(size=order_size)
            return
        if open_short:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} k1={k1:.2f} d1={d1:.2f}')
            order_size = size if self.position.size <= 0 else abs(float(self.position.size)) + size
            self.sell(size=order_size)
            return

        if reverse_to_long:
            self.signal_count += 1
            self.log(f'close short by crossover close={close_price:.2f} k1={k1:.2f} d1={d1:.2f}')
        elif reverse_to_short:
            self.signal_count += 1
            self.log(f'close long by crossover close={close_price:.2f} k1={k1:.2f} d1={d1:.2f}')

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
