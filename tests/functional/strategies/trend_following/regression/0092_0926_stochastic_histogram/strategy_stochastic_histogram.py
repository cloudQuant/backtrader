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


MA_METHODS = {
    'sma': bt.indicators.SimpleMovingAverage,
    'ema': bt.indicators.ExponentialMovingAverage,
    'smma': bt.indicators.SmoothedMovingAverage,
    'lwma': bt.indicators.WeightedMovingAverage,
}


class StochasticHistogramIndicator(bt.Indicator):
    lines = ('main', 'signal', 'hist_base', 'color_state')
    params = dict(
        k_period=5,
        d_period=3,
        slowing=3,
        ma_method='sma',
        high_level=60,
        low_level=40,
    )

    def __init__(self):
        self.addminperiod(int(self.p.k_period) + int(self.p.slowing) + int(self.p.d_period) + 2)

    def _fast_k_at(self, i, high_array, low_array, close_array):
        period = max(1, int(self.p.k_period))
        if i - period + 1 < 0:
            return float('nan')
        lowest = min(float(low_array[idx]) for idx in range(i - period + 1, i + 1))
        highest = max(float(high_array[idx]) for idx in range(i - period + 1, i + 1))
        denom = highest - lowest
        return 100.0 * (float(close_array[i]) - lowest) / denom if denom else 50.0

    def _ma_value(self, values, period, previous=None):
        if not values:
            return float('nan')
        mode = str(self.p.ma_method).strip().lower()
        value = float(values[-1])
        if mode in {'ema', 'mode_ema'}:
            if previous is None or previous != previous:
                return value
            alpha = 2.0 / (period + 1.0)
            return previous + alpha * (value - previous)
        if mode in {'smma', 'mode_smma'}:
            if previous is None or previous != previous:
                return value
            return ((period - 1.0) * previous + value) / period
        if mode in {'lwma', 'wma', 'mode_lwma'}:
            weights = list(range(1, len(values) + 1))
            return sum(v * w for v, w in zip(values, weights)) / sum(weights)
        return sum(values) / len(values)

    def next(self):
        k_period = max(1, int(self.p.k_period))
        slowing = max(1, int(self.p.slowing))
        d_period = max(1, int(self.p.d_period))
        fast_values = []
        for ago in range(slowing - 1, -1, -1):
            if len(self.data) <= ago + k_period - 1:
                return
            low_values = [float(self.data.low[-ago - shift]) for shift in range(k_period)]
            high_values = [float(self.data.high[-ago - shift]) for shift in range(k_period)]
            lowest = min(low_values)
            highest = max(high_values)
            denom = highest - lowest
            fast_values.append(100.0 * (float(self.data.close[-ago]) - lowest) / denom if denom else 50.0)
        prev_main = float(self.lines.main[-1]) if len(self) > 1 else None
        prev_signal = float(self.lines.signal[-1]) if len(self) > 1 else None
        main = self._ma_value(fast_values, slowing, prev_main)
        self.lines.main[0] = main
        signal_values = [float(self.lines.main[-ago]) for ago in range(min(len(self), d_period) - 1, 0, -1)]
        signal_values.append(main)
        self.lines.signal[0] = self._ma_value(signal_values, d_period, prev_signal)
        color = 1.0
        if main > float(self.p.high_level):
            color = 0.0
        elif main < float(self.p.low_level):
            color = 2.0
        self.lines.color_state[0] = color
        self.lines.hist_base[0] = 50.0

    def once(self, start, end):
        high_array = self.data.high.array
        low_array = self.data.low.array
        close_array = self.data.close.array
        main_line = self.lines.main.array
        signal_line = self.lines.signal.array
        hist_base_line = self.lines.hist_base.array
        color_state_line = self.lines.color_state.array
        for line in (main_line, signal_line, hist_base_line, color_state_line):
            while len(line) < end:
                line.append(float('nan'))

        slowing = max(1, int(self.p.slowing))
        d_period = max(1, int(self.p.d_period))
        actual_end = min(end, len(high_array), len(low_array), len(close_array))
        fast_values = [self._fast_k_at(i, high_array, low_array, close_array) for i in range(actual_end)]
        main_values = []
        signal_values_all = []
        prev_main = None
        prev_signal = None
        for i in range(actual_end):
            main_start = max(0, i - slowing + 1)
            main = self._ma_value(fast_values[main_start:i + 1], slowing, prev_main)
            main_values.append(main)
            prev_main = main
            signal_start = max(0, i - d_period + 1)
            signal = self._ma_value(main_values[signal_start:i + 1], d_period, prev_signal)
            signal_values_all.append(signal)
            prev_signal = signal
            if i < start:
                continue
            main_line[i] = main
            signal_line[i] = signal_values_all[i]
            color = 1.0
            if main > float(self.p.high_level):
                color = 0.0
            elif main < float(self.p.low_level):
                color = 2.0
            color_state_line[i] = color
            hist_base_line[i] = 50.0


class ExpStochasticHistogramStrategy(bt.Strategy):
    params = dict(
        trend_mode='cross',
        k_period=5,
        d_period=3,
        slowing=3,
        ma_method='sma',
        high_level=60,
        low_level=40,
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
        self.indicator = StochasticHistogramIndicator(
            self.signal_data,
            k_period=self.p.k_period,
            d_period=self.p.d_period,
            slowing=self.p.slowing,
            ma_method=self.p.ma_method,
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
        min_signal_bars = int(self.p.k_period) + int(self.p.d_period) + int(self.p.slowing) + prev_ago + 6
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
