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
    })
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
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class LaguerreIndicator(bt.Indicator):
    lines = ('value', 'color_state')
    params = dict(gamma=0.7, high_level=85, middle_level=50, low_level=15)

    def __init__(self):
        self._l0 = 0.0
        self._l1 = 0.0
        self._l2 = 0.0
        self._l3 = 0.0
        self._initialized = False
        self.addminperiod(3)

    def _zone(self, value):
        if value > float(self.p.high_level):
            return 'high'
        if value > float(self.p.middle_level):
            return 'high_mid'
        if value < float(self.p.low_level):
            return 'low'
        return 'low_mid'

    def _color_from_state(self, curr_zone, prev_zone, prev_color):
        if curr_zone == 'high':
            return 1.0
        if curr_zone == 'high_mid':
            if prev_zone == 'high':
                return 2.0
            if prev_zone == 'high_mid':
                return prev_color
            return 1.0
        if curr_zone == 'low_mid':
            if prev_zone in ('high', 'high_mid'):
                return 2.0
            if prev_zone == 'low_mid':
                return prev_color
            return 1.0
        if curr_zone == 'low':
            return 2.0
        return prev_color

    def next(self):
        price = float(self.data.close[0])
        gamma = float(self.p.gamma)
        prev_l0, prev_l1, prev_l2, prev_l3 = self._l0, self._l1, self._l2, self._l3

        if not self._initialized:
            self._l0 = price
            self._l1 = price
            self._l2 = price
            self._l3 = price
            self._initialized = True
        else:
            self._l0 = (1.0 - gamma) * price + gamma * prev_l0
            self._l1 = -gamma * self._l0 + prev_l0 + gamma * prev_l1
            self._l2 = -gamma * self._l1 + prev_l1 + gamma * prev_l2
            self._l3 = -gamma * self._l2 + prev_l2 + gamma * prev_l3

        cu = 0.0
        cd = 0.0
        pairs = ((self._l0, self._l1), (self._l1, self._l2), (self._l2, self._l3))
        for a, b in pairs:
            if a >= b:
                cu += a - b
            else:
                cd += b - a
        value = 0.0
        if (cu + cd) > 1e-12:
            value = 100.0 * cu / (cu + cd)

        prev_value = float(self.lines.value[-1]) if len(self) > 1 else value
        prev_color = float(self.lines.color_state[-1]) if len(self) > 1 else 1.0
        curr_zone = self._zone(value)
        prev_zone = self._zone(prev_value)
        color = self._color_from_state(curr_zone, prev_zone, prev_color)

        self.lines.value[0] = value
        self.lines.color_state[0] = color


class ExpLaguerreStrategy(bt.Strategy):
    params = dict(
        gamma=0.7,
        high_level=85,
        middle_level=50,
        low_level=15,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.0001,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=60,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = LaguerreIndicator(
            self.signal_data,
            gamma=self.p.gamma,
            high_level=self.p.high_level,
            middle_level=self.p.middle_level,
            low_level=self.p.low_level,
        )
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        point_value = float(self.p.point)
        stop_distance = self.p.stop_loss_points * point_value if self.p.stop_loss_points > 0 else None
        take_distance = self.p.take_profit_points * point_value if self.p.take_profit_points > 0 else None
        entry_price = float(self.position.price)

        if self.position.size > 0:
            if stop_distance is not None and close_price <= entry_price - stop_distance:
                self.log(f'close long by stop loss close={close_price:.5f} entry={entry_price:.5f}')
                self.close()
                return True
            if take_distance is not None and close_price >= entry_price + take_distance:
                self.log(f'close long by take profit close={close_price:.5f} entry={entry_price:.5f}')
                self.close()
                return True
        elif self.position.size < 0:
            if stop_distance is not None and close_price >= entry_price + stop_distance:
                self.log(f'close short by stop loss close={close_price:.5f} entry={entry_price:.5f}')
                self.close()
                return True
            if take_distance is not None and close_price <= entry_price - take_distance:
                self.log(f'close short by take profit close={close_price:.5f} entry={entry_price:.5f}')
                self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return

        if self._check_exit_levels():
            return

        current_ago = max(int(self.p.signal_bar) - 1, 0)
        prev_ago = current_ago + 1
        if len(self.signal_data) < prev_ago + 4:
            return

        current_signal_len = len(self.signal_data)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        prev_color = float(self.indicator.color_state[-prev_ago])
        curr_color = float(self.indicator.color_state[-current_ago]) if current_ago else float(self.indicator.color_state[0])
        if not math.isfinite(prev_color) or not math.isfinite(curr_color):
            return

        close_price = float(self.base.close[0])
        size = float(self.p.fixed_lot)
        if size <= 0:
            return

        if self.position.size < 0 and curr_color == 1.0 and self.p.sell_pos_close:
            self.log(f'close short by laguerre color={curr_color} close={close_price:.5f}')
            self.close()
        if self.position.size > 0 and curr_color == 2.0 and self.p.buy_pos_close:
            self.log(f'close long by laguerre color={curr_color} close={close_price:.5f}')
            self.close()

        if prev_color == 2.0 and curr_color == 1.0:
            self.signal_count += 1
            self.log(f'buy signal color={prev_color}->{curr_color} close={close_price:.5f}')
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if prev_color == 1.0 and curr_color == 2.0:
            self.signal_count += 1
            self.log(f'sell signal color={prev_color}->{curr_color} close={close_price:.5f}')
            if self.position.size >= 0 and self.p.sell_pos_open:
                self.sell(size=size)

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
