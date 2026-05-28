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


class AroonSignalFeed(btfeeds.PandasData):
    lines = ('up_signal', 'dn_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('up_signal', 6), ('dn_signal', 7),
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


def build_aroon_signal_frame(df, indicator_minutes, high_level, low_level, aroon_period):
    signal_df = build_resampled_frame(df, indicator_minutes)
    up_signals = [math.nan] * len(signal_df)
    dn_signals = [math.nan] * len(signal_df)
    last_trend = 0

    highs = signal_df['high'].astype(float).tolist()
    lows = signal_df['low'].astype(float).tolist()

    for idx in range(len(signal_df)):
        if idx + 1 < int(aroon_period):
            continue

        start = idx - int(aroon_period) + 1
        window_highs = highs[start:idx + 1]
        window_lows = lows[start:idx + 1]
        high_pos = max(range(len(window_highs)), key=lambda pos: window_highs[pos])
        low_pos = min(range(len(window_lows)), key=lambda pos: window_lows[pos])
        periods_since_high = len(window_highs) - 1 - high_pos
        periods_since_low = len(window_lows) - 1 - low_pos

        bulls = 100.0 - (periods_since_high + 0.5) * 100.0 / float(aroon_period)
        bears = 100.0 - (periods_since_low + 0.5) * 100.0 / float(aroon_period)

        if bulls > float(high_level) and bears < float(low_level):
            if last_trend == -1:
                range_window_start = max(0, idx - 9)
                ranges = [abs(highs[pos] - lows[pos]) for pos in range(range_window_start, idx + 1)]
                range_value = (sum(ranges) / len(ranges)) * 0.5 if ranges else 0.0
                up_signals[idx] = lows[idx] - range_value
            last_trend = 1
            continue

        if bulls < float(low_level) and bears > float(high_level):
            if last_trend == 1:
                range_window_start = max(0, idx - 9)
                ranges = [abs(highs[pos] - lows[pos]) for pos in range(range_window_start, idx + 1)]
                range_value = (sum(ranges) / len(ranges)) * 0.5 if ranges else 0.0
                dn_signals[idx] = highs[idx] + range_value
            last_trend = -1
            continue

    signal_df = signal_df.copy()
    signal_df['up_signal'] = up_signals
    signal_df['dn_signal'] = dn_signals
    return signal_df


class AroonSignalStrategy(bt.Strategy):
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
        high_level=85,
        low_level=15,
        aroon_period=9,
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

    def _is_signal(self, value):
        return math.isfinite(value) and not math.isnan(value)

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
        if len(self.signal) < signal_bar:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        up_value = self._line_value(self.signal.up_signal, recent_ago)
        dn_value = self._line_value(self.signal.dn_signal, recent_ago)
        up_signal = self._is_signal(up_value)
        dn_signal = self._is_signal(dn_value)
        if not up_signal and not dn_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if up_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if dn_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f}')
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
