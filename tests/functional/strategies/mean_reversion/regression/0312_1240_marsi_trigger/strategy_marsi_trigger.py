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


class MaRsiTriggerFeed(btfeeds.PandasData):
    lines = ('trend', 'last_trend', 'ma_fast', 'ma_slow', 'rsi_fast', 'rsi_slow')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('trend', 6), ('last_trend', 7), ('ma_fast', 8), ('ma_slow', 9), ('rsi_fast', 10), ('rsi_slow', 11),
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


def applied_price(df, code):
    open_ = df['open'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    code = int(code)
    if code == 0:
        return close
    if code == 1:
        return open_
    if code == 2:
        return high
    if code == 3:
        return low
    if code == 4:
        return (high + low) / 2.0
    if code == 5:
        return (high + low + close) / 3.0
    if code == 6:
        return (high + low + 2.0 * close) / 4.0
    return close


def moving_average(series, period, method):
    period = int(period)
    method = int(method)
    if method == 0:
        return series.rolling(period, min_periods=period).mean()
    if method == 1:
        return series.ewm(span=period, adjust=False, min_periods=period).mean()
    if method == 2:
        return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    if method == 3:
        weights = np.arange(1, period + 1, dtype=float)
        return series.rolling(period, min_periods=period).apply(lambda values: float(np.dot(values, weights) / weights.sum()), raw=True)
    return series.rolling(period, min_periods=period).mean()


def rsi_wilder(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / int(period), adjust=False, min_periods=int(period)).mean()
    avg_loss = loss.ewm(alpha=1.0 / int(period), adjust=False, min_periods=int(period)).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)
    return rsi


def build_marsi_trigger_frame(
    df,
    indicator_minutes,
    n_period_rsi,
    n_rsi_price,
    n_period_rsi_long,
    n_rsi_price_long,
    n_period_ma,
    n_ma_type,
    n_ma_price,
    n_period_ma_long,
    n_ma_type_long,
    n_ma_price_long,
):
    signal_df = build_resampled_frame(df, indicator_minutes)

    ma_fast = moving_average(applied_price(signal_df, n_ma_price), n_period_ma, n_ma_type)
    ma_slow = moving_average(applied_price(signal_df, n_ma_price_long), n_period_ma_long, n_ma_type_long)
    rsi_fast = rsi_wilder(applied_price(signal_df, n_rsi_price), n_period_rsi)
    rsi_slow = rsi_wilder(applied_price(signal_df, n_rsi_price_long), n_period_rsi_long)

    trend = []
    last_trend = []
    prev_nonzero = 0
    for idx in range(len(signal_df)):
        value = math.nan
        mf = ma_fast.iloc[idx]
        ms = ma_slow.iloc[idx]
        rf = rsi_fast.iloc[idx]
        rs = rsi_slow.iloc[idx]
        if math.isfinite(mf) and math.isfinite(ms) and math.isfinite(rf) and math.isfinite(rs):
            res = 0
            if mf > ms:
                res = 1
            elif mf < ms:
                res = -1
            if rf > rs:
                res += 1
            elif rf < rs:
                res -= 1
            value = max(min(res, 1), -1)
        trend.append(value)
        last_trend.append(prev_nonzero if prev_nonzero != 0 else math.nan)
        if math.isfinite(value) and int(value) != 0:
            prev_nonzero = int(value)

    signal_df = signal_df.copy()
    signal_df['trend'] = trend
    signal_df['last_trend'] = last_trend
    signal_df['ma_fast'] = ma_fast
    signal_df['ma_slow'] = ma_slow
    signal_df['rsi_fast'] = rsi_fast
    signal_df['rsi_slow'] = rsi_slow
    return signal_df


class MaRsiTriggerStrategy(bt.Strategy):
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
        n_period_rsi=3,
        n_rsi_price=6,
        n_period_rsi_long=13,
        n_rsi_price_long=4,
        n_period_ma=5,
        n_ma_type=1,
        n_ma_price=0,
        n_period_ma_long=10,
        n_ma_type_long=1,
        n_ma_price_long=0,
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
        if len(self.signal) < signal_bar:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        trend = self._line_value(self.signal.trend, recent_ago)
        if not self._has_value(trend) or int(trend) == 0:
            return

        last_trend = self._line_value(self.signal.last_trend, recent_ago)
        current_trend = int(round(trend))
        previous_trend = int(round(last_trend)) if self._has_value(last_trend) else 0

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if current_trend > 0:
            self.signal_count += 1
            self.log(f'bull trend close={close_price:.2f} trend={current_trend} last_trend={previous_trend}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if previous_trend < 0 and self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if current_trend < 0:
            self.signal_count += 1
            self.log(f'bear trend close={close_price:.2f} trend={current_trend} last_trend={previous_trend}')
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
            if previous_trend > 0 and self.position.size >= 0 and self.p.sell_pos_open:
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
