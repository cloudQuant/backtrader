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


class AmlFeed(btfeeds.PandasData):
    lines = ('aml', 'state')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('aml', 6), ('state', 7),
    )


def build_resampled_frame(df, indicator_minutes):
    rule = f'{int(indicator_minutes)}min'
    signal_df = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    signal_df = signal_df.dropna(subset=['open', 'high', 'low', 'close']).copy()
    signal_df['openinterest'] = signal_df['openinterest'].fillna(0)
    return signal_df


def recount_array_zero_pos(co_arr, size):
    max1 = size - 1
    count = co_arr[-1]
    count -= 1
    if count < 0:
        count = max1
    new_arr = []
    for iii in range(size):
        numb = iii + count
        if numb > max1:
            numb -= size
        new_arr.append(numb)
    new_arr[-1] = count
    return new_arr


def range_value(period, start, highs, lows):
    window_high = highs[start:start + period]
    window_low = lows[start:start + period]
    return max(window_high) - min(window_low)


def build_aml_frame(df, indicator_minutes, fractal, lag, point):
    signal_df = build_resampled_frame(df, indicator_minutes)
    n = len(signal_df)
    min_rates_total = int(fractal) + int(lag)
    if n <= min_rates_total + 1:
        out = signal_df.copy()
        out['aml'] = math.nan
        out['state'] = math.nan
        return out

    high = signal_df['high'].astype(float).tolist()
    low = signal_df['low'].astype(float).tolist()
    open_ = signal_df['open'].astype(float).tolist()
    close = signal_df['close'].astype(float).tolist()

    smooth_values = [math.nan] * n
    aml_values = [math.nan] * n
    state_values = [math.nan] * n
    threshold = float(lag * lag) * float(point)

    for idx in range(n):
        if idx < min_rates_total:
            continue

        start_r1 = idx - int(fractal) + 1
        start_r2 = idx - 2 * int(fractal) + 1
        start_r3 = idx - 2 * int(fractal) + 1
        if start_r2 < 0:
            continue

        r1 = range_value(int(fractal), start_r1, high, low) / float(fractal)
        r2 = range_value(int(fractal), start_r2, high, low) / float(fractal)
        r3 = range_value(2 * int(fractal), start_r3, high, low) / float(2 * int(fractal))

        dim = 0.0
        if r1 + r2 > 0 and r3 > 0:
            dim = (math.log(r1 + r2) - math.log(r3)) * 1.44269504088896

        alpha = math.exp(-float(lag) * (dim - 1.0))
        alpha = min(alpha, 1.0)
        alpha = max(alpha, 0.01)

        price = (high[idx] + low[idx] + 2.0 * open_[idx] + 2.0 * close[idx]) / 6.0
        prev_smooth = smooth_values[idx - 1] if idx > 0 and math.isfinite(smooth_values[idx - 1]) else 0.0
        smooth_values[idx] = alpha * price + (1.0 - alpha) * prev_smooth

        smooth_lag = smooth_values[idx - int(lag)] if idx - int(lag) >= 0 and math.isfinite(smooth_values[idx - int(lag)]) else smooth_values[idx]
        prev_aml = aml_values[idx - 1] if idx > 0 and math.isfinite(aml_values[idx - 1]) else smooth_values[idx]
        if abs(smooth_values[idx] - smooth_lag) >= threshold:
            aml_values[idx] = smooth_values[idx]
        else:
            aml_values[idx] = prev_aml

        prev_state = state_values[idx - 1] if idx > 0 and math.isfinite(state_values[idx - 1]) else 1.0
        state_values[idx] = prev_state
        if aml_values[idx] > prev_aml:
            state_values[idx] = 2.0
        if aml_values[idx] < prev_aml:
            state_values[idx] = 0.0

    out = signal_df.copy()
    out['aml'] = aml_values
    out['state'] = state_values
    return out


class AmlStrategy(bt.Strategy):
    params = dict(
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        mm=-0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
        fractal=6,
        lag=7,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
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

    def _line_value(self, line, ago):
        return float(line[-ago]) if ago else float(line[0])

    def _position_size(self, price):
        if self.p.mm < 0:
            return abs(float(self.p.mm))
        if price <= 0:
            return 0.0
        cash = self.broker.getcash()
        return round((cash * float(self.p.mm)) / price, 4)

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

        signal_bar = max(int(self.p.signal_bar), 1)
        if len(self.signal) < signal_bar + 1:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        prev_ago = signal_bar
        state_recent = self._line_value(self.signal.state, recent_ago)
        state_prev = self._line_value(self.signal.state, prev_ago)
        if not math.isfinite(state_recent) or not math.isfinite(state_prev):
            return
        state_recent = int(round(state_recent))
        state_prev = int(round(state_prev))

        buy_signal = state_recent == 2 and state_prev != 2
        sell_signal = state_recent == 0 and state_prev != 0
        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} state={state_recent}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} state={state_recent}')
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
