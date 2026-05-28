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


class WPRHistogramIndicator(bt.Indicator):
    lines = ('value', 'midline', 'color_state')
    params = dict(wpr_period=14, high_level=-30, low_level=-70)

    def __init__(self):
        self.addminperiod(self.p.wpr_period)

    def next(self):
        period = int(self.p.wpr_period)
        highest_high = max(float(self.data.high[-i]) for i in range(period))
        lowest_low = min(float(self.data.low[-i]) for i in range(period))
        close = float(self.data.close[0])
        denom = highest_high - lowest_low
        if abs(denom) <= 1e-12:
            value = -50.0
        else:
            value = -100.0 * (highest_high - close) / denom

        color = 1.0
        if value > float(self.p.high_level):
            color = 0.0
        elif value < float(self.p.low_level):
            color = 2.0

        self.lines.value[0] = value
        self.lines.midline[0] = -50.0
        self.lines.color_state[0] = color


class ExpWPRHistogramStrategy(bt.Strategy):
    params = dict(
        wpr_period=14,
        high_level=-30,
        low_level=-70,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = WPRHistogramIndicator(
            self.signal_data,
            wpr_period=self.p.wpr_period,
            high_level=self.p.high_level,
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
        if len(self.base) < 2:
            return

        if self._check_exit_levels():
            return

        current_ago = max(int(self.p.signal_bar) - 1, 0)
        prev_ago = current_ago + 1
        min_signal_bars = self.p.wpr_period + prev_ago + 1
        if len(self.signal_data) < min_signal_bars:
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

        if curr_color == 0.0 and prev_color > 0.0:
            self.signal_count += 1
            self.log(f'buy signal color={prev_color}->{curr_color} close={close_price:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if curr_color == 2.0 and prev_color < 2.0:
            self.signal_count += 1
            self.log(f'sell signal color={prev_color}->{curr_color} close={close_price:.2f}')
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
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
