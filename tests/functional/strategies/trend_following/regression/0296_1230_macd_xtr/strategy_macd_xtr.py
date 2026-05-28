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

SOURCE_VOLUME = 0
SOURCE_ATR = 1
SOURCE_STDEV = 2
VOLUME_TICK = 0
VOLUME_REAL = 1


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


class MacdXtrFeed(btfeeds.PandasData):
    lines = ('state', 'macd', 'level')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('state', 6), ('macd', 7), ('level', 8),
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


def ema(series, period):
    period = max(1, int(period))
    return pd.Series(series, dtype=float).ewm(span=period, adjust=False, min_periods=period).mean()


def atr_wilder(df, period):
    period = int(period)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def stddev_sma(series, period):
    return pd.Series(series, dtype=float).rolling(int(period), min_periods=int(period)).std(ddof=0)


def ema_fba(series_value, ema_prev, period, fba):
    if period == 1:
        return series_value
    alpha = period
    if period > 1:
        alpha = 2.0 / (1.0 + period)
    ema_value = alpha * series_value + (1.0 - alpha) * ema_prev
    if fba == 0:
        return ema_value
    if fba == 1:
        return ema_value if series_value > ema_prev else series_value
    if fba == -1:
        return ema_value if series_value < ema_prev else series_value
    return ema_value


def build_macd_xtr_frame(df, indicator_minutes, fast_ma, slow_ma, source, source_period, front_period, back_period, x_volatility, sens, volume_type, point):
    signal_df = build_resampled_frame(df, indicator_minutes)
    close = signal_df['close'].astype(float)
    macd = ema(close, fast_ma) - ema(close, slow_ma)

    source = int(source)
    volume_type = int(volume_type)
    source_period = int(source_period)
    front_period = int(front_period)
    back_period = int(back_period)

    if source == SOURCE_VOLUME:
        volume_series = signal_df['volume'].astype(float) if volume_type == VOLUME_TICK else signal_df['openinterest'].astype(float)
        raw_vlt = ema(volume_series, source_period)
    elif source == SOURCE_ATR:
        raw_vlt = atr_wilder(signal_df, source_period)
    else:
        raw_vlt = stddev_sma(close, source_period)

    if front_period == back_period:
        fba = 0
        per0 = 2.0 / (1.0 + front_period)
        per1 = 1.0
    elif front_period < back_period:
        fba = -1
        per0 = 2.0 / (1.0 + front_period)
        per1 = 2.0 / (1.0 + back_period)
    else:
        fba = 1
        per0 = 2.0 / (1.0 + back_period)
        per1 = 2.0 / (1.0 + front_period)

    sensitivity = float(sens) if source == SOURCE_VOLUME else float(sens) * float(point)

    ema0_prev = None
    ema1_prev = None
    state = []
    levels = []
    macd_values = macd.tolist()
    raw_values = raw_vlt.tolist()
    for idx in range(len(signal_df)):
        raw_value = raw_values[idx]
        macd_value = macd_values[idx]
        if not math.isfinite(raw_value) or not math.isfinite(macd_value):
            state.append(math.nan)
            levels.append(math.nan)
            continue
        if ema0_prev is None:
            ema0_prev = raw_value
            ema1_prev = raw_value
        ema0 = ema_fba(raw_value, ema0_prev, per0, 0)
        ema1 = ema_fba(ema0, ema1_prev, per1, fba)
        ema0_prev = ema0
        ema1_prev = ema1

        vlt = max(ema1, sensitivity)
        level = max(sensitivity, vlt * float(x_volatility))
        color_state = 1
        if macd_value > level:
            color_state = 2
        if macd_value < -level:
            color_state = 0
        state.append(float(color_state))
        levels.append(level)

    signal_df = signal_df.copy()
    signal_df['state'] = state
    signal_df['macd'] = macd
    signal_df['level'] = levels
    return signal_df


class MacdXtrStrategy(bt.Strategy):
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
        fast_ma=12,
        slow_ma=26,
        source=1,
        source_period=22,
        front_period=1,
        back_period=444,
        x_volatility=0.5,
        sens=0,
        volume_type=0,
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
        close_neutral = state_recent == 1

        if close_neutral:
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()

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
