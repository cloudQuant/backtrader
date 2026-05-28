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


class _RollingWeightedAverage4:
    def __init__(self):
        self.values = []

    def update(self, value):
        self.values.append(float(value))
        if len(self.values) > 4:
            self.values.pop(0)
        if len(self.values) < 4:
            return 0.0
        return (self.values[3] + 2.0 * self.values[2] + 2.0 * self.values[1] + self.values[0]) / 6.0


class _RollingSimpleAverage:
    def __init__(self, period):
        self.period = max(int(period), 1)
        self.values = []

    def update(self, value):
        self.values.append(float(value))
        if len(self.values) > self.period:
            self.values.pop(0)
        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)


class RVIHistogramIndicator(bt.Indicator):
    lines = ('main', 'signal', 'hist_base', 'color_state')
    params = dict(rvi_period=14, high_level=0.3, low_level=-0.3)

    def __init__(self):
        self._co_avg4 = _RollingWeightedAverage4()
        self._hl_avg4 = _RollingWeightedAverage4()
        self._num_sma = _RollingSimpleAverage(self.p.rvi_period)
        self._den_sma = _RollingSimpleAverage(self.p.rvi_period)
        self._main_avg4 = _RollingWeightedAverage4()
        self.addminperiod(int(self.p.rvi_period) + 6)

    def next(self):
        co = float(self.data.close[0]) - float(self.data.open[0])
        hl = float(self.data.high[0]) - float(self.data.low[0])
        weighted_co = self._co_avg4.update(co)
        weighted_hl = self._hl_avg4.update(hl)
        num = self._num_sma.update(weighted_co)
        den = self._den_sma.update(weighted_hl)
        main = num / den if abs(den) > 1e-12 else 0.0
        signal = self._main_avg4.update(main)

        color = 1.0
        if main > float(self.p.high_level):
            color = 0.0
        elif main < float(self.p.low_level):
            color = 2.0

        self.lines.main[0] = main
        self.lines.signal[0] = signal
        self.lines.hist_base[0] = 0.0
        self.lines.color_state[0] = color


class ExpRVIHistogramStrategy(bt.Strategy):
    params = dict(
        trend_mode='cross',
        rvi_period=14,
        high_level=0.3,
        low_level=-0.3,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.0001,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = RVIHistogramIndicator(
            self.signal_data,
            rvi_period=self.p.rvi_period,
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

    def _signal_levels(self, prev_ago, current_ago):
        prev_color = float(self.indicator.color_state[-prev_ago])
        curr_color = float(self.indicator.color_state[-current_ago]) if current_ago else float(self.indicator.color_state[0])
        if not math.isfinite(prev_color) or not math.isfinite(curr_color):
            return False, False
        buy_open = curr_color == 0.0 and prev_color > 0.0 and self.p.buy_pos_open
        sell_open = curr_color == 2.0 and prev_color < 2.0 and self.p.sell_pos_open
        return buy_open, sell_open

    def _signal_cross(self, prev_ago, current_ago):
        prev_main = float(self.indicator.main[-prev_ago])
        prev_signal = float(self.indicator.signal[-prev_ago])
        curr_main = float(self.indicator.main[-current_ago]) if current_ago else float(self.indicator.main[0])
        curr_signal = float(self.indicator.signal[-current_ago]) if current_ago else float(self.indicator.signal[0])
        values = (prev_main, prev_signal, curr_main, curr_signal)
        if any(not math.isfinite(v) for v in values):
            return False, False
        buy_open = prev_main <= prev_signal and curr_main > curr_signal and self.p.buy_pos_open
        sell_open = prev_main >= prev_signal and curr_main < curr_signal and self.p.sell_pos_open
        return buy_open, sell_open

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return

        if self._check_exit_levels():
            return

        current_ago = max(int(self.p.signal_bar) - 1, 0)
        prev_ago = current_ago + 1
        min_signal_bars = int(self.p.rvi_period) + prev_ago + 8
        if len(self.signal_data) < min_signal_bars:
            return

        current_signal_len = len(self.signal_data)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        mode = str(self.p.trend_mode).strip().lower()
        if mode == 'levels':
            buy_open, sell_open = self._signal_levels(prev_ago, current_ago)
        else:
            buy_open, sell_open = self._signal_cross(prev_ago, current_ago)

        close_price = float(self.base.close[0])
        size = float(self.p.fixed_lot)
        if size <= 0:
            return

        if buy_open:
            self.signal_count += 1
            self.log(f'buy signal mode={mode} close={close_price:.5f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0:
                self.buy(size=size)
            return

        if sell_open:
            self.signal_count += 1
            self.log(f'sell signal mode={mode} close={close_price:.5f}')
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
            if self.position.size >= 0:
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
