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

MODE_BREAKDOWN = 0
MODE_TWIST = 1
MODE_DISPOSITION = 2


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


class OracleFeed(btfeeds.PandasData):
    lines = ('oracle_value', 'signal_value')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('oracle_value', 6), ('signal_value', 7),
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


def resolve_applied_price(df, price_code):
    open_ = df['open'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    code = int(price_code)
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


def wilder_rsi(series, period):
    values = pd.Series(series, dtype=float)
    period = int(period)
    delta = values.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    result = [math.nan] * len(values)
    if len(values) <= period:
        return pd.Series(result, index=values.index, dtype=float)

    avg_gain = gain.iloc[1:period + 1].mean()
    avg_loss = loss.iloc[1:period + 1].mean()
    if math.isfinite(avg_gain) and math.isfinite(avg_loss):
        if avg_loss == 0:
            result[period] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[period] = 100.0 - (100.0 / (1.0 + rs))

    for idx in range(period + 1, len(values)):
        avg_gain = ((avg_gain * (period - 1)) + gain.iloc[idx]) / period
        avg_loss = ((avg_loss * (period - 1)) + loss.iloc[idx]) / period
        if avg_loss == 0:
            result[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[idx] = 100.0 - (100.0 / (1.0 + rs))
    return pd.Series(result, index=values.index, dtype=float)


def cci_from_price(series, period):
    values = pd.Series(series, dtype=float)
    period = int(period)
    sma = values.rolling(period, min_periods=period).mean()
    mean_dev = values.rolling(period, min_periods=period).apply(lambda x: float(np.mean(np.abs(x - np.mean(x)))), raw=True)
    denom = 0.015 * mean_dev.replace(0.0, np.nan)
    return (values - sma) / denom


def build_oracle_frame(df, indicator_minutes, oracle_period, applied_price, smooth, recount):
    signal_df = build_resampled_frame(df, indicator_minutes)
    oracle_period = int(oracle_period)
    smooth = int(smooth)
    recount = bool(recount)

    price_series = resolve_applied_price(signal_df, applied_price)
    rsi = wilder_rsi(price_series, oracle_period)
    cci = cci_from_price(price_series, oracle_period)

    rsi_ts = rsi.to_numpy(dtype=float)[::-1]
    cci_ts = cci.to_numpy(dtype=float)[::-1]
    n = len(signal_df)
    oracle_ts = np.full(n, np.nan, dtype=float)
    signal_ts = np.full(n, np.nan, dtype=float)
    maxbar = int(n - oracle_period - 4 - 1)
    if maxbar >= 0:
        for bar in range(maxbar, -1, -1):
            required_rsi = [bar, bar + 1, bar + 2, bar + 3]
            if any(idx >= n or not math.isfinite(rsi_ts[idx]) for idx in required_rsi):
                continue
            if recount:
                cci_idx1 = bar - 1 if bar > 0 else bar
                cci_idx2 = bar - 2 if bar > 1 else (bar - 1 if bar > 0 else bar)
                cci_idx3 = bar - 3 if bar > 2 else (bar - 2 if bar > 1 else (bar - 1 if bar > 0 else bar))
            else:
                cci_idx1 = bar
                cci_idx2 = bar
                cci_idx3 = bar
            cci_indices = [bar, cci_idx1, cci_idx2, cci_idx3]
            if any(idx < 0 or idx >= n or not math.isfinite(cci_ts[idx]) for idx in cci_indices):
                continue

            div0 = cci_ts[bar] - rsi_ts[bar]
            ddiv = div0
            div1 = cci_ts[cci_idx1] - rsi_ts[bar + 1] - ddiv
            ddiv += div1
            div2 = cci_ts[cci_idx2] - rsi_ts[bar + 2] - ddiv
            ddiv += div2
            div3 = cci_ts[cci_idx3] - rsi_ts[bar + 3] - ddiv
            oracle_value = max(div0, div1, div2, div3) + min(div0, div1, div2, div3)
            oracle_ts[bar] = oracle_value

            window = oracle_ts[bar:bar + smooth]
            if len(window) == smooth and np.isfinite(window).all():
                signal_ts[bar] = float(window.mean())

    signal_df = signal_df.copy()
    signal_df['oracle_value'] = oracle_ts[::-1]
    signal_df['signal_value'] = signal_ts[::-1]
    return signal_df


class OracleStrategy(bt.Strategy):
    params = dict(
        mode=MODE_TWIST,
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
        oracle_period=55,
        applied_price=0,
        smooth=8,
        recount=True,
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
        if len(self.signal) < signal_bar + 2:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        prev_ago = signal_bar
        older_ago = signal_bar + 1
        signal_recent = self._line_value(self.signal.signal_value, recent_ago)
        signal_prev = self._line_value(self.signal.signal_value, prev_ago)
        oracle_recent = self._line_value(self.signal.oracle_value, recent_ago)
        oracle_prev = self._line_value(self.signal.oracle_value, prev_ago)

        buy_signal = False
        sell_signal = False
        mode = int(self.p.mode)
        if mode == MODE_BREAKDOWN:
            if not all(math.isfinite(v) for v in [signal_recent, signal_prev]):
                return
            buy_signal = signal_recent > 0.0 and signal_prev <= 0.0
            sell_signal = signal_recent < 0.0 and signal_prev >= 0.0
        elif mode == MODE_TWIST:
            signal_older = self._line_value(self.signal.signal_value, older_ago)
            if not all(math.isfinite(v) for v in [signal_recent, signal_prev, signal_older]):
                return
            buy_signal = signal_recent > signal_prev and signal_older >= signal_prev
            sell_signal = signal_recent < signal_prev and signal_older <= signal_prev
        else:
            if not all(math.isfinite(v) for v in [signal_recent, signal_prev, oracle_recent, oracle_prev]):
                return
            buy_signal = signal_recent < oracle_recent and signal_prev >= oracle_prev
            sell_signal = signal_recent > oracle_recent and signal_prev <= oracle_prev

        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} oracle={oracle_recent:.2f} signal={signal_recent:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} oracle={oracle_recent:.2f} signal={signal_recent:.2f}')
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
