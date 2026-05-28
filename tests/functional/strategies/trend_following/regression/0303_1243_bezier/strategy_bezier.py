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


class BezierFeed(btfeeds.PandasData):
    lines = ('bezier',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('bezier', 6),
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


def factorial(value):
    result = 1
    for i in range(2, int(value) + 1):
        result *= i
    return result


def applied_price(df, code):
    open_ = df['open'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)

    code = int(code)
    if code == 1:
        return close
    if code == 2:
        return open_
    if code == 3:
        return high
    if code == 4:
        return low
    if code == 5:
        return (high + low) / 2.0
    if code == 6:
        return (close + high + low) / 3.0
    if code == 7:
        return (2.0 * close + high + low) / 4.0
    if code == 8:
        return (open_ + close) / 2.0
    if code == 9:
        return (open_ + close + high + low) / 4.0
    if code == 10:
        return pd.Series(
            [high.iloc[i] if close.iloc[i] > open_.iloc[i] else low.iloc[i] if close.iloc[i] < open_.iloc[i] else close.iloc[i] for i in range(len(df))],
            index=df.index,
            dtype=float,
        )
    if code == 11:
        return pd.Series(
            [
                (high.iloc[i] + close.iloc[i]) / 2.0 if close.iloc[i] > open_.iloc[i]
                else (low.iloc[i] + close.iloc[i]) / 2.0 if close.iloc[i] < open_.iloc[i]
                else close.iloc[i]
                for i in range(len(df))
            ],
            index=df.index,
            dtype=float,
        )
    return close


def build_bezier_frame(df, indicator_minutes, bperiod, t, ipc, price_shift_points=0, point=0.01):
    signal_df = build_resampled_frame(df, indicator_minutes)
    period = int(bperiod)
    t = min(max(float(t), 0.0), 1.0)
    price_shift = float(point) * float(price_shift_points)
    src = applied_price(signal_df, ipc)
    bezier_values = [math.nan] * len(signal_df)

    period_factorial = factorial(period)
    weights = []
    for iii in range(period, -1, -1):
        weight = (period_factorial / (factorial(iii) * factorial(period - iii))) * (t ** iii) * ((1.0 - t) ** (period - iii))
        weights.append(weight)

    src_values = src.astype(float).tolist()
    for idx in range(len(signal_df)):
        if idx < period + 1:
            continue
        value = 0.0
        start = idx - period
        for offset, weight in enumerate(weights):
            value += src_values[start + offset] * weight + price_shift
        bezier_values[idx] = value

    signal_df = signal_df.copy()
    signal_df['bezier'] = bezier_values
    return signal_df


class BezierStrategy(bt.Strategy):
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
        bperiod=8,
        t=0.5,
        ipc=7,
        price_shift_points=0,
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

    def _has_value(self, value):
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
        if len(self.signal) < signal_bar + 2:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        mid_ago = signal_bar
        old_ago = signal_bar + 1
        recent = self._line_value(self.signal.bezier, recent_ago)
        mid = self._line_value(self.signal.bezier, mid_ago)
        old = self._line_value(self.signal.bezier, old_ago)
        if not self._has_value(recent) or not self._has_value(mid) or not self._has_value(old):
            return

        buy_signal = old > mid and recent > mid
        sell_signal = old < mid and recent < mid
        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} old={old:.2f} mid={mid:.2f} recent={recent:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} old={old:.2f} mid={mid:.2f} recent={recent:.2f}')
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
