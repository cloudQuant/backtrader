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


class TrendEnvelopesFeed(btfeeds.PandasData):
    lines = ('up_trend', 'down_trend', 'up_signal', 'down_signal', 'atr', 'ma')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('up_trend', 6), ('down_trend', 7), ('up_signal', 8), ('down_signal', 9), ('atr', 10), ('ma', 11),
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


def atr_wilder(high_series, low_series, close_series, period):
    period = int(period)
    high = pd.Series(high_series, dtype=float).reset_index(drop=True)
    low = pd.Series(low_series, dtype=float).reset_index(drop=True)
    close = pd.Series(close_series, dtype=float).reset_index(drop=True)
    n = len(close)
    tr = [math.nan] * n
    atr = [math.nan] * n
    for idx in range(1, n):
        tr[idx] = max(
            high.iloc[idx] - low.iloc[idx],
            abs(high.iloc[idx] - close.iloc[idx - 1]),
            abs(low.iloc[idx] - close.iloc[idx - 1]),
        )
    if n <= period:
        return pd.Series(atr, dtype=float)
    seed = sum(v for v in tr[1:period + 1] if math.isfinite(v)) / period
    atr[period] = seed
    for idx in range(period + 1, n):
        atr[idx] = ((atr[idx - 1] * (period - 1)) + tr[idx]) / period
    return pd.Series(atr, dtype=float)


def moving_average(series, period, method='ema'):
    period = int(period)
    s = pd.Series(series, dtype=float)
    if method == 'sma':
        return s.rolling(period).mean()
    if method == 'smma':
        result = [math.nan] * len(s)
        if len(s) <= period:
            return pd.Series(result, dtype=float)
        seed = s.iloc[:period].mean()
        result[period - 1] = seed
        prev = seed
        for idx in range(period, len(s)):
            prev = (prev * (period - 1) + s.iloc[idx]) / period
            result[idx] = prev
        return pd.Series(result, dtype=float)
    if method == 'lwma':
        weights = list(range(1, period + 1))
        weight_sum = sum(weights)
        result = [math.nan] * len(s)
        for idx in range(period - 1, len(s)):
            window = s.iloc[idx - period + 1:idx + 1].tolist()
            result[idx] = sum(w * v for w, v in zip(weights, window)) / weight_sum
        return pd.Series(result, dtype=float)
    return s.ewm(span=period, adjust=False).mean()


def build_trend_envelopes_frame(df, indicator_minutes, ma_period, ma_method, deviation_pct, atr_period, atr_sensitivity):
    signal_df = build_resampled_frame(df, indicator_minutes)
    close = signal_df['close'].astype(float).reset_index(drop=True)
    atr = atr_wilder(signal_df['high'], signal_df['low'], signal_df['close'], atr_period)
    ma = moving_average(close, ma_period, method=ma_method)
    n = len(signal_df)
    up_trend = [math.nan] * n
    down_trend = [math.nan] * n
    up_signal = [math.nan] * n
    down_signal = [math.nan] * n
    min_rates_total = max(int(atr_period), int(ma_period)) + 1
    prev_smax = 0.0
    prev_smin = 999999999.9
    prev_trend = 0

    for idx in range(n):
        atr_value = float(atr.iloc[idx]) if math.isfinite(float(atr.iloc[idx])) else math.nan
        ma_value = float(ma.iloc[idx]) if math.isfinite(float(ma.iloc[idx])) else math.nan
        if idx < min_rates_total or not math.isfinite(atr_value) or not math.isfinite(ma_value):
            continue

        smax = (1.0 + float(deviation_pct) / 100.0) * ma_value
        smin = (1.0 - float(deviation_pct) / 100.0) * ma_value
        trend = prev_trend
        price = float(close.iloc[idx])
        if price > prev_smax:
            trend = 1
        if price < prev_smin:
            trend = -1

        if trend > 0:
            if smin < prev_smin:
                smin = prev_smin
            up_trend[idx] = smin
            if prev_trend < 0:
                up_signal[idx] = smin - float(atr_sensitivity) * atr_value
        else:
            if smax > prev_smax:
                smax = prev_smax
            down_trend[idx] = smax
            if prev_trend > 0:
                down_signal[idx] = smax + float(atr_sensitivity) * atr_value

        prev_smax = smax
        prev_smin = smin
        prev_trend = trend

    out = signal_df.copy()
    out['up_trend'] = up_trend
    out['down_trend'] = down_trend
    out['up_signal'] = up_signal
    out['down_signal'] = down_signal
    out['atr'] = list(atr)
    out['ma'] = list(ma)
    return out


class TrendEnvelopesStrategy(bt.Strategy):
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
        ma_period=14,
        ma_method='ema',
        deviation_pct=0.2,
        atr_period=15,
        atr_sensitivity=0.5,
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

    def _is_valid(self, value):
        return math.isfinite(value) and value != 0.0

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
        up_trend = self._line_value(self.signal.up_trend, ago)
        down_trend = self._line_value(self.signal.down_trend, ago)
        up_signal = self._line_value(self.signal.up_signal, ago)
        down_signal = self._line_value(self.signal.down_signal, ago)
        has_up_signal = self._is_valid(up_signal)
        has_down_signal = self._is_valid(down_signal)
        has_up_trend = self._is_valid(up_trend)
        has_down_trend = self._is_valid(down_trend)

        buy_signal = has_up_signal
        sell_signal = has_down_signal
        close_short = sell_signal or has_up_trend
        close_long = buy_signal or has_down_trend
        if not buy_signal and not sell_signal and not close_short and not close_long:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if close_short and self.position.size < 0 and self.p.sell_pos_close:
            self.close()
        if close_long and self.position.size > 0 and self.p.buy_pos_close:
            self.close()
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} up_signal={up_signal:.2f}')
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} down_signal={down_signal:.2f}')
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
