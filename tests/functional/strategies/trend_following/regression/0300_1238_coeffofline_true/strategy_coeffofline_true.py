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
import numpy as np
import pandas as pd

INVERTED_SYMBOLS = {
    'EURUSD', 'GBPUSD', 'USDCAD', 'USDCHF',
    'EURGBP', 'EURCHF', 'AUDUSD', 'GBPCHF',
}


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


class CoeffOfLineTrueFeed(btfeeds.PandasData):
    lines = ('value',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('value', 6),
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


def smma_series(series, period):
    period = int(period)
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def build_coeffofline_true_frame(df, indicator_minutes, smma_period, symbol):
    signal_df = build_resampled_frame(df, indicator_minutes)
    smma_period = int(smma_period)

    median_price = (signal_df['high'].astype(float) + signal_df['low'].astype(float)) / 2.0
    smma = smma_series(median_price, smma_period).shift(3)

    high_ts = signal_df['high'].astype(float).to_numpy()[::-1]
    low_ts = signal_df['low'].astype(float).to_numpy()[::-1]
    smma_ts = smma.to_numpy()[::-1]
    values_ts = np.full(len(signal_df), np.nan, dtype=float)

    n = smma_period
    M = n * (n + 1) / 2.0
    N = n * (n + 1) * (2 * n + 1) / 6.0
    sign = -1.0 if str(symbol).upper() in INVERTED_SYMBOLS else 1.0

    for bar in range(0, len(signal_df) - n + 1):
        ty_var = 0.0
        zy_var = 0.0
        t_indicator_var = 0.0
        z_indicator_var = 0.0
        valid = True

        for cnt in range(n, 0, -1):
            iii = bar + cnt - 1
            price = (high_ts[iii] + low_ts[iii]) / 2.0
            count = n + 1 - cnt
            smma_value = smma_ts[iii]
            if not math.isfinite(price) or not math.isfinite(smma_value):
                valid = False
                break
            ty_var += price
            zy_var += price * count
            t_indicator_var += smma_value
            z_indicator_var += smma_value * count

        if not valid or M == 0:
            continue

        ay = (ty_var + (N - 2.0 * zy_var) * n / M) / M
        a_indicator = (t_indicator_var + (N - 2.0 * z_indicator_var) * n / M) / M
        if math.isfinite(ay) and math.isfinite(a_indicator) and abs(a_indicator) > 1e-12:
            ratio = ay / a_indicator
            if math.isfinite(ratio) and ratio > 0:
                values_ts[bar] = sign * 1000.0 * math.log(ratio)

    signal_df = signal_df.copy()
    signal_df['value'] = values_ts[::-1]
    return signal_df


class CoeffOfLineTrueStrategy(bt.Strategy):
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
        smma_period=5,
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
        recent = self._line_value(self.signal.value, recent_ago)
        prev = self._line_value(self.signal.value, prev_ago)
        if not math.isfinite(recent) or not math.isfinite(prev):
            return

        buy_signal = recent > 0.0 and prev < 0.0
        sell_signal = recent < 0.0 and prev > 0.0
        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} value={recent:.2f} prev={prev:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} value={recent:.2f} prev={prev:.2f}')
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
