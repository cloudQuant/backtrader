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


class TrendValueFeed(btfeeds.PandasData):
    lines = ('up_trend', 'dn_trend', 'up_signal', 'dn_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('up_trend', 6), ('dn_trend', 7), ('up_signal', 8), ('dn_signal', 9),
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


def ema(series, period):
    return pd.Series(series, dtype=float).ewm(span=int(period), adjust=False, min_periods=int(period)).mean()


def build_trendvalue_frame(df, indicator_minutes, ma_period, shift_percent, atr_period, atr_sensitivity):
    signal_df = build_resampled_frame(df, indicator_minutes)
    atr = atr_wilder(signal_df, atr_period)
    hma = ema(signal_df['high'].astype(float), ma_period)
    lma = ema(signal_df['low'].astype(float), ma_period)

    up_trend = [math.nan] * len(signal_df)
    dn_trend = [math.nan] * len(signal_df)
    up_signal = [math.nan] * len(signal_df)
    dn_signal = [math.nan] * len(signal_df)

    high_moving_prev = math.nan
    low_moving_prev = math.nan
    trend = 0

    for idx in range(len(signal_df)):
        atr_value = float(atr.iloc[idx]) if math.isfinite(float(atr.iloc[idx])) else math.nan
        hma_value = float(hma.iloc[idx]) if math.isfinite(float(hma.iloc[idx])) else math.nan
        lma_value = float(lma.iloc[idx]) if math.isfinite(float(lma.iloc[idx])) else math.nan
        close_value = float(signal_df['close'].iloc[idx])
        if not all(math.isfinite(v) for v in [atr_value, hma_value, lma_value]):
            continue

        atr_shift = atr_value * float(atr_sensitivity)
        high_moving = hma_value * (1.0 + float(shift_percent) / 100.0) + atr_shift
        low_moving = lma_value * (1.0 - float(shift_percent) / 100.0) - atr_shift

        if not math.isfinite(high_moving_prev) or not math.isfinite(low_moving_prev):
            high_moving_prev = high_moving
            low_moving_prev = low_moving
            continue

        if close_value > high_moving_prev:
            trend = 1
        if close_value < low_moving_prev:
            trend = -1

        current_up = math.nan
        current_dn = math.nan
        if trend > 0:
            low_moving = max(low_moving, low_moving_prev)
            current_up = low_moving
        if trend < 0:
            high_moving = min(high_moving, high_moving_prev)
            current_dn = high_moving

        up_trend[idx] = current_up
        dn_trend[idx] = current_dn

        prev_up = up_trend[idx - 1] if idx > 0 else math.nan
        prev_dn = dn_trend[idx - 1] if idx > 0 else math.nan
        if math.isnan(prev_up) and math.isfinite(current_up):
            up_signal[idx] = current_up
        if math.isnan(prev_dn) and math.isfinite(current_dn):
            dn_signal[idx] = current_dn

        low_moving_prev = low_moving
        high_moving_prev = high_moving

    signal_df = signal_df.copy()
    signal_df['up_trend'] = up_trend
    signal_df['dn_trend'] = dn_trend
    signal_df['up_signal'] = up_signal
    signal_df['dn_signal'] = dn_signal
    return signal_df


class TrendValueStrategy(bt.Strategy):
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
        ma_period=13,
        shift_percent=0.0,
        atr_period=15,
        atr_sensitivity=1.5,
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

    @staticmethod
    def _has_value(value):
        return math.isfinite(value) and abs(value) > 1e-12

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

        ago = signal_bar - 1
        up_signal = self._line_value(self.signal.up_signal, ago)
        dn_signal = self._line_value(self.signal.dn_signal, ago)
        up_trend = self._line_value(self.signal.up_trend, ago)
        dn_trend = self._line_value(self.signal.dn_trend, ago)

        buy_signal = self._has_value(up_signal)
        sell_signal = self._has_value(dn_signal)
        buy_close = self._has_value(dn_signal) or (not buy_signal and self._has_value(dn_trend))
        sell_close = self._has_value(up_signal) or (not sell_signal and self._has_value(up_trend))

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)

        if buy_close and self.position.size > 0 and self.p.buy_pos_close:
            self.close()
            if buy_signal:
                self.log(f'close long by sell signal close={close_price:.2f}')
        if sell_close and self.position.size < 0 and self.p.sell_pos_close:
            self.close()
            if sell_signal:
                self.log(f'close short by buy signal close={close_price:.2f}')

        if size <= 0:
            return

        if buy_signal and self.position.size <= 0 and self.p.buy_pos_open:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} up_signal={up_signal:.2f}')
            self.buy(size=size)
            return

        if sell_signal and self.position.size >= 0 and self.p.sell_pos_open:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} dn_signal={dn_signal:.2f}')
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
