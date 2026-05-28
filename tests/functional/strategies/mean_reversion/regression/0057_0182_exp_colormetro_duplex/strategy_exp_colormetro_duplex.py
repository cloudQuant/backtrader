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


class ColorMetroFeed(btfeeds.PandasData):
    lines = ('mplus', 'mminus', 'rsi')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('mplus', 6), ('mminus', 7), ('rsi', 8),
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


def rsi_wilder(close_series, period):
    period = int(period)
    close = pd.Series(close_series, dtype=float).reset_index(drop=True)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = [math.nan] * len(close)
    avg_loss = [math.nan] * len(close)
    rsi = [math.nan] * len(close)
    if len(close) <= period:
        return pd.Series(rsi, dtype=float)

    first_gain = gain.iloc[1:period + 1].mean()
    first_loss = loss.iloc[1:period + 1].mean()
    avg_gain[period] = first_gain
    avg_loss[period] = first_loss
    if first_loss == 0:
        rsi[period] = 100.0
    else:
        rs = first_gain / first_loss
        rsi[period] = 100.0 - 100.0 / (1.0 + rs)

    for idx in range(period + 1, len(close)):
        avg_gain[idx] = ((avg_gain[idx - 1] * (period - 1)) + gain.iloc[idx]) / period
        avg_loss[idx] = ((avg_loss[idx - 1] * (period - 1)) + loss.iloc[idx]) / period
        if avg_loss[idx] == 0:
            rsi[idx] = 100.0
        else:
            rs = avg_gain[idx] / avg_loss[idx]
            rsi[idx] = 100.0 - 100.0 / (1.0 + rs)
    return pd.Series(rsi, dtype=float)


def build_color_metro_frame(df, indicator_minutes, period_rsi, step_size_fast, step_size_slow):
    signal_df = build_resampled_frame(df, indicator_minutes)
    rsi_series = rsi_wilder(signal_df['close'].astype(float), period_rsi)
    n = len(signal_df)
    mplus = [math.nan] * n
    mminus = [math.nan] * n
    fmax1 = 999999.0
    fmin1 = 999999.0
    smin1 = 999999.0
    smax1 = -999999.0
    ftrend = 0
    strend = 0
    initialized = False

    for idx in range(n):
        rsi0 = float(rsi_series.iloc[idx]) if math.isfinite(float(rsi_series.iloc[idx])) else math.nan
        if not math.isfinite(rsi0):
            continue
        if not initialized:
            fmin1 = 999999.0
            fmax1 = -999999.0
            smin1 = 999999.0
            smax1 = -999999.0
            ftrend = 0
            strend = 0
            initialized = True

        fmax0 = rsi0 + 2.0 * float(step_size_fast)
        fmin0 = rsi0 - 2.0 * float(step_size_fast)
        if rsi0 > fmax1:
            ftrend = 1
        if rsi0 < fmin1:
            ftrend = -1
        if ftrend > 0 and fmin0 < fmin1:
            fmin0 = fmin1
        if ftrend < 0 and fmax0 > fmax1:
            fmax0 = fmax1

        smax0 = rsi0 + 2.0 * float(step_size_slow)
        smin0 = rsi0 - 2.0 * float(step_size_slow)
        if rsi0 > smax1:
            strend = 1
        if rsi0 < smin1:
            strend = -1
        if strend > 0 and smin0 < smin1:
            smin0 = smin1
        if strend < 0 and smax0 > smax1:
            smax0 = smax1

        if ftrend > 0:
            mplus[idx] = fmin0 + float(step_size_fast)
        elif ftrend < 0:
            mplus[idx] = fmax0 - float(step_size_fast)

        if strend > 0:
            mminus[idx] = smin0 + float(step_size_slow)
        elif strend < 0:
            mminus[idx] = smax0 - float(step_size_slow)

        fmin1 = fmin0
        fmax1 = fmax0
        smin1 = smin0
        smax1 = smax0

    signal_df = signal_df.copy()
    signal_df['mplus'] = mplus
    signal_df['mminus'] = mminus
    signal_df['rsi'] = list(rsi_series)
    return signal_df


class ExpColorMetroDuplexStrategy(bt.Strategy):
    params = dict(
        l_signal_bar=1,
        s_signal_bar=1,
        l_stop_loss_points=1000,
        l_take_profit_points=2000,
        s_stop_loss_points=1000,
        s_take_profit_points=2000,
        l_mm=-0.1,
        s_mm=-0.1,
        point=0.01,
        l_pos_open=True,
        l_pos_close=True,
        s_pos_open=True,
        s_pos_close=True,
        indicator_minutes=240,
        period_rsi=7,
        step_size_fast=5,
        step_size_slow=15,
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
        self._pending_side = None
        self._current_stop = None
        self._current_take_profit = None

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    @staticmethod
    def _line_value(line, ago):
        return float(line[-ago]) if ago else float(line[0])

    def _position_size(self, mm, price):
        if mm < 0:
            return abs(float(mm))
        if price <= 0:
            return 0.0
        cash = self.broker.getcash()
        return round((cash * float(mm)) / price, 4)

    def _set_risk_levels(self, side, entry_price):
        point = float(self.p.point)
        if side == 'long':
            self._current_stop = entry_price - self.p.l_stop_loss_points * point if self.p.l_stop_loss_points else None
            self._current_take_profit = entry_price + self.p.l_take_profit_points * point if self.p.l_take_profit_points else None
        else:
            self._current_stop = entry_price + self.p.s_stop_loss_points * point if self.p.s_stop_loss_points else None
            self._current_take_profit = entry_price - self.p.s_take_profit_points * point if self.p.s_take_profit_points else None

    def _clear_risk_levels(self):
        self._current_stop = None
        self._current_take_profit = None

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        if self.position.size > 0:
            if self._current_stop is not None and close_price <= self._current_stop:
                self.log(f'close long stop={self._current_stop:.2f}')
                self.close()
                return True
            if self._current_take_profit is not None and close_price >= self._current_take_profit:
                self.log(f'close long take_profit={self._current_take_profit:.2f}')
                self.close()
                return True
        if self.position.size < 0:
            if self._current_stop is not None and close_price >= self._current_stop:
                self.log(f'close short stop={self._current_stop:.2f}')
                self.close()
                return True
            if self._current_take_profit is not None and close_price <= self._current_take_profit:
                self.log(f'close short take_profit={self._current_take_profit:.2f}')
                self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return

        if self._check_exit_levels():
            return

        max_signal_bar = max(int(self.p.l_signal_bar), int(self.p.s_signal_bar), 1)
        if len(self.signal) < max_signal_bar + 1:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        l_recent = max(int(self.p.l_signal_bar), 1) - 1
        l_prev = max(int(self.p.l_signal_bar), 1)
        s_recent = max(int(self.p.s_signal_bar), 1) - 1
        s_prev = max(int(self.p.s_signal_bar), 1)

        plus_l_recent = self._line_value(self.signal.mplus, l_recent)
        minus_l_recent = self._line_value(self.signal.mminus, l_recent)
        plus_l_prev = self._line_value(self.signal.mplus, l_prev)
        minus_l_prev = self._line_value(self.signal.mminus, l_prev)
        plus_s_recent = self._line_value(self.signal.mplus, s_recent)
        minus_s_recent = self._line_value(self.signal.mminus, s_recent)
        plus_s_prev = self._line_value(self.signal.mplus, s_prev)
        minus_s_prev = self._line_value(self.signal.mminus, s_prev)

        if not all(math.isfinite(v) for v in [plus_l_recent, minus_l_recent, plus_l_prev, minus_l_prev, plus_s_recent, minus_s_recent, plus_s_prev, minus_s_prev]):
            return

        buy_signal = plus_l_recent > minus_l_recent and plus_l_prev <= minus_l_prev
        sell_signal = plus_s_recent < minus_s_recent and plus_s_prev >= minus_s_prev
        close_price = float(self.base.close[0])

        if buy_signal:
            self.signal_count += 1
            size = self._position_size(self.p.l_mm, close_price)
            if size <= 0:
                return
            self.log(f'buy signal close={close_price:.2f} mplus={plus_l_recent:.2f} mminus={minus_l_recent:.2f}')
            if self.position.size < 0 and self.p.s_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.l_pos_open:
                self._pending_side = 'long'
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            size = self._position_size(self.p.s_mm, close_price)
            if size <= 0:
                return
            self.log(f'sell signal close={close_price:.2f} mplus={plus_s_recent:.2f} mminus={minus_s_recent:.2f}')
            if self.position.size > 0 and self.p.l_pos_close:
                self.close()
            if self.position.size >= 0 and self.p.s_pos_open:
                self._pending_side = 'short'
                self.sell(size=size)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self._pending_side == 'long' and self.position.size > 0:
                self._set_risk_levels('long', order.executed.price)
            elif self._pending_side == 'short' and self.position.size < 0:
                self._set_risk_levels('short', order.executed.price)
            elif self.position.size == 0:
                self._clear_risk_levels()
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self._pending_side = None

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
        self._clear_risk_levels()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
