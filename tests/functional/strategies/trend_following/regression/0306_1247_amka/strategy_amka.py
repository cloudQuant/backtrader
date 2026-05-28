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


class AMkASignalFeed(btfeeds.PandasData):
    lines = ('ama', 'dn_signal', 'up_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('ama', 6), ('dn_signal', 7), ('up_signal', 8),
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


def point_to_digits(point):
    point_value = float(point)
    if point_value <= 0:
        return 2
    return max(0, int(round(-math.log10(point_value))))


def build_amka_signal_frame(df, indicator_minutes, ama_period, fast_ma_period, slow_ma_period, g_power, dk, point):
    signal_df = build_resampled_frame(df, indicator_minutes)
    price_series = signal_df['close'].astype(float).tolist()
    ama_values = [0.0] * len(price_series)
    dn_signals = [0.0] * len(price_series)
    up_signals = [0.0] * len(price_series)

    digits = point_to_digits(point)
    slow_sc = 2.0 / (float(slow_ma_period) + 1.0)
    fast_sc = 2.0 / (float(fast_ma_period) + 1.0)
    dsc = fast_sc - slow_sc
    epsilon = float(point) / 10000.0 if float(point) > 0 else 1e-6

    first_ama = int(ama_period) + 2
    if len(price_series) > first_ama:
        ama = price_series[first_ama - 1]
        for bar in range(first_ama, len(price_series)):
            noise = epsilon
            for idx in range(int(ama_period)):
                price0 = price_series[bar - idx]
                price1 = price_series[bar - idx - 1]
                noise += abs(price0 - price1)

            price0 = price_series[bar]
            price1 = price_series[bar - int(ama_period)]
            signal = abs(price0 - price1)
            er = signal / noise if noise else 0.0
            ersc = er * dsc
            ssc = ersc + slow_sc
            ama = ama + (math.pow(ssc, float(g_power)) * (price0 - ama))
            ama_values[bar] = ama

    first_signal = 2 * int(ama_period) + 6
    if len(price_series) > first_signal:
        for bar in range(first_signal, len(price_series)):
            d_ama = [ama_values[bar - idx] - ama_values[bar - idx - 1] for idx in range(int(ama_period))]
            sma_dif = sum(d_ama) / float(ama_period)
            variance = sum(math.pow(value - sma_dif, 2) for value in d_ama) / float(ama_period)
            stdev = math.sqrt(variance)
            dama = round(d_ama[0], digits + 2)
            filter_value = round(float(dk) * stdev, digits + 2)
            if dama < -filter_value:
                dn_signals[bar] = ama_values[bar]
            if dama > filter_value:
                up_signals[bar] = ama_values[bar]

    signal_df = signal_df.copy()
    signal_df['ama'] = ama_values
    signal_df['dn_signal'] = dn_signals
    signal_df['up_signal'] = up_signals
    return signal_df


class AMkAStrategy(bt.Strategy):
    params = dict(
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        mm=0.1,
        mm_mode='lot',
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
        ama_period=9,
        fast_ma_period=2,
        slow_ma_period=30,
        g_power=2.0,
        dk=1.0,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
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

    def _is_signal(self, line, ago):
        value = self._line_value(line, ago)
        return math.isfinite(value) and value != 0.0

    def _position_size(self, price):
        mm_mode = str(self.p.mm_mode).strip().lower()
        if mm_mode == 'lot':
            return abs(float(self.p.mm))
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

    def _find_last_trend(self, start_ago):
        for ago in range(start_ago, len(self.signal_data)):
            if self._is_signal(self.signal_data.dn_signal, ago):
                return -1
            if self._is_signal(self.signal_data.up_signal, ago):
                return 1
        return 0

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return

        if self._check_exit_levels():
            return

        signal_bar = max(int(self.p.signal_bar), 1)
        if len(self.signal_data) <= signal_bar:
            return

        current_signal_len = len(self.signal_data)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        start_ago = signal_bar
        up_signal = self._is_signal(self.signal_data.up_signal, recent_ago)
        dn_signal = self._is_signal(self.signal_data.dn_signal, recent_ago)
        if not up_signal and not dn_signal:
            return

        last_trend = self._find_last_trend(start_ago)
        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if up_signal:
            self.signal_count += 1
            self.log(f'buy signal last_trend={last_trend} close={close_price:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.p.buy_pos_open and last_trend < 0 and self.position.size <= 0:
                self.buy(size=size)
            return

        if dn_signal:
            self.signal_count += 1
            self.log(f'sell signal last_trend={last_trend} close={close_price:.2f}')
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
            if self.p.sell_pos_open and last_trend > 0 and self.position.size >= 0:
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
