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


class EaMarsiSignalFeed(btfeeds.PandasData):
    lines = ('slow_line', 'fast_line')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('slow_line', 6), ('fast_line', 7),
    )


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


def rsi_wilder(series, period):
    period = int(period)
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)
    return rsi


def ema_rsi_va(series, rsi_period, ema_periods):
    price_series = series.astype(float)
    rsi_period = int(rsi_period)
    ema_periods = float(ema_periods)
    rsi = rsi_wilder(price_series, rsi_period)
    values = np.full(len(price_series), np.nan, dtype=float)
    seed_index = rsi_period * 2 - 1
    if seed_index >= len(price_series):
        return pd.Series(values, index=price_series.index)
    values[seed_index] = float(price_series.iloc[seed_index])
    for i in range(seed_index + 1, len(price_series)):
        rsi_value = float(rsi.iloc[i]) if pd.notna(rsi.iloc[i]) else math.nan
        if not math.isfinite(rsi_value):
            values[i] = values[i - 1]
            continue
        rsvoltl = abs(rsi_value - 50.0) + 1.0
        multi = (5.0 + 100.0 / rsi_period) / (0.06 + 0.92 * rsvoltl + 0.02 * (rsvoltl ** 2))
        pdsx = max(multi * ema_periods, 1.0)
        alpha = 2.0 / (pdsx + 1.0)
        values[i] = float(price_series.iloc[i]) * alpha + values[i - 1] * (1.0 - alpha)
    return pd.Series(values, index=price_series.index)


def build_signal_frame(df, slow_rsi_period, slow_ema_periods, slow_price, fast_rsi_period, fast_ema_periods, fast_price):
    signal_df = df.copy()
    signal_df['slow_line'] = ema_rsi_va(applied_price(signal_df, slow_price), slow_rsi_period, slow_ema_periods)
    signal_df['fast_line'] = ema_rsi_va(applied_price(signal_df, fast_price), fast_rsi_period, fast_ema_periods)
    return signal_df


class EaMarsiStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        tp_points=0.0,
        sl_points=0.0,
        use_multpl=False,
        max_drawdown=10000.0,
        point=0.01,
        signal_bar=1,
        max_lot=None,
        slow_rsi_period=310,
        slow_ema_periods=40,
        slow_price=0,
        fast_rsi_period=200,
        fast_ema_periods=50,
        fast_price=0,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
        self.order = None
        self.pending_reverse = None
        self.stop_price = None
        self.take_price = None
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _position_size(self):
        size = float(self.p.lots)
        if bool(self.p.use_multpl):
            base_value = float(self.broker.getvalue())
            max_drawdown = max(float(self.p.max_drawdown), 1e-9)
            size = round(float(self.p.lots) * base_value / max_drawdown, 2)
        max_lot = self.p.max_lot
        if max_lot is not None:
            size = min(size, float(max_lot))
        return max(size, 0.0)

    def _set_exit_levels(self, entry_price, direction):
        point = float(self.p.point)
        sl_distance = float(self.p.sl_points) * point if float(self.p.sl_points) > 0 else None
        tp_distance = float(self.p.tp_points) * point if float(self.p.tp_points) > 0 else None
        if direction > 0:
            self.stop_price = entry_price - sl_distance if sl_distance is not None else None
            self.take_price = entry_price + tp_distance if tp_distance is not None else None
        else:
            self.stop_price = entry_price + sl_distance if sl_distance is not None else None
            self.take_price = entry_price - tp_distance if tp_distance is not None else None

    def _clear_exit_levels(self):
        self.stop_price = None
        self.take_price = None

    def _enter(self, direction):
        if self.order is not None:
            return
        size = self._position_size()
        if size <= 0:
            return
        if direction > 0:
            self.log(f'open long size={size:.2f}')
            self.order = self.buy(size=size)
        else:
            self.log(f'open short size={size:.2f}')
            self.order = self.sell(size=size)

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            hit_stop = self.stop_price is not None and low <= self.stop_price
            hit_take = self.take_price is not None and high >= self.take_price
            if hit_stop or hit_take:
                reason = 'stop loss' if hit_stop else 'take profit'
                self.log(f'close long by {reason}')
                self.pending_reverse = None
                self.order = self.close()
                return True
        elif self.position.size < 0:
            hit_stop = self.stop_price is not None and high >= self.stop_price
            hit_take = self.take_price is not None and low <= self.take_price
            if hit_stop or hit_take:
                reason = 'stop loss' if hit_stop else 'take profit'
                self.log(f'close short by {reason}')
                self.pending_reverse = None
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2 or len(self.signal) < 2:
            return
        if self.order is not None:
            return
        if self.pending_reverse is not None and not self.position:
            direction = self.pending_reverse
            self.pending_reverse = None
            self._enter(direction)
            return
        if self._check_exit_levels():
            return
        recent_ago = max(int(self.p.signal_bar), 1) - 1
        prev_ago = recent_ago + 1
        if len(self.signal) <= prev_ago:
            return
        slow_now = float(self.signal.slow_line[-recent_ago]) if recent_ago else float(self.signal.slow_line[0])
        fast_now = float(self.signal.fast_line[-recent_ago]) if recent_ago else float(self.signal.fast_line[0])
        slow_prev = float(self.signal.slow_line[-prev_ago])
        fast_prev = float(self.signal.fast_line[-prev_ago])
        if not all(math.isfinite(v) for v in [slow_now, fast_now, slow_prev, fast_prev]):
            return
        bullish_cross = slow_prev > fast_prev and slow_now <= fast_now
        bearish_cross = slow_prev < fast_prev and slow_now >= fast_now
        if not bullish_cross and not bearish_cross:
            return
        self.signal_count += 1
        if not self.position:
            if bullish_cross:
                self._enter(1)
            elif bearish_cross:
                self._enter(-1)
            return
        if self.position.size > 0 and bearish_cross:
            self.log('reverse long to short')
            self.pending_reverse = -1
            self.order = self.close()
            return
        if self.position.size < 0 and bullish_cross:
            self.log('reverse short to long')
            self.pending_reverse = 1
            self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            self.order = None
            if self.position:
                direction = 1 if self.position.size > 0 else -1
                self._set_exit_levels(float(order.executed.price), direction)
            else:
                self._clear_exit_levels()
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            self.order = None
            self.pending_reverse = None

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
        self._clear_exit_levels()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
