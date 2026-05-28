from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'real_volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'tick_volume': 'sum',
        'real_volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def weighted_moving_average(series, period):
    period = int(max(period, 1))
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def smma(series, period):
    period = int(max(period, 1))
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < period:
        return pd.Series(out, index=series.index)
    seed = np.nanmean(values[:period])
    out[period - 1] = seed
    for idx in range(period, len(values)):
        prev = out[idx - 1]
        curr = values[idx]
        if np.isnan(prev) or np.isnan(curr):
            continue
        out[idx] = (prev * (period - 1) + curr) / period
    return pd.Series(out, index=series.index)


def smooth_series(series, method, period):
    method = str(method or 'MODE_LWMA').upper()
    period = int(max(period, 1))
    if method in ('MODE_SMA', 'MODE_SMA_'):
        return series.rolling(period).mean()
    if method in ('MODE_EMA', 'MODE_EMA_'):
        return series.ewm(span=period, adjust=False).mean()
    if method in ('MODE_SMMA', 'MODE_SMMA_'):
        return smma(series, period)
    return weighted_moving_average(series, period)


def price_series(frame, applied_price):
    key = str(applied_price or 'PRICE_CLOSE_').upper()
    if key in ('PRICE_CLOSE', 'PRICE_CLOSE_'):
        return frame['close']
    if key in ('PRICE_OPEN', 'PRICE_OPEN_'):
        return frame['open']
    if key in ('PRICE_HIGH', 'PRICE_HIGH_'):
        return frame['high']
    if key in ('PRICE_LOW', 'PRICE_LOW_'):
        return frame['low']
    if key in ('PRICE_MEDIAN', 'PRICE_MEDIAN_'):
        return (frame['high'] + frame['low']) / 2.0
    if key in ('PRICE_TYPICAL', 'PRICE_TYPICAL_'):
        return (frame['high'] + frame['low'] + frame['close']) / 3.0
    if key in ('PRICE_WEIGHTED', 'PRICE_WEIGHTED_'):
        return (frame['high'] + frame['low'] + 2.0 * frame['close']) / 4.0
    if key in ('PRICE_SIMPL', 'PRICE_SIMPL_'):
        return (frame['open'] + frame['close']) / 2.0
    if key in ('PRICE_QUARTER', 'PRICE_QUARTER_'):
        return (frame['high'] + frame['low'] + frame['open'] + frame['close']) / 4.0
    if key in ('PRICE_TRENDFOLLOW0', 'PRICE_TRENDFOLLOW0_'):
        return pd.Series(np.where(frame['close'] >= frame['open'], frame['high'], frame['low']), index=frame.index)
    if key in ('PRICE_TRENDFOLLOW1', 'PRICE_TRENDFOLLOW1_'):
        return pd.Series(np.where(frame['close'] >= frame['open'], frame['low'], frame['high']), index=frame.index)
    if key in ('PRICE_DEMARK', 'PRICE_DEMARK_'):
        cond_up = frame['close'] > frame['open']
        cond_dn = frame['close'] < frame['open']
        return pd.Series(
            np.where(
                cond_up,
                frame['high'] * 2 + frame['low'] + frame['close'],
                np.where(cond_dn, frame['high'] + frame['low'] * 2 + frame['close'], frame['high'] + frame['low'] + frame['close'] * 2),
            ) / 4.0,
            index=frame.index,
        )
    return frame['close']


def compute_slope_direction_line(frame, ma_method1='MODE_LWMA', length1=12, phase1=15, ma_method2='MODE_SMA', phase2=15, ipc='PRICE_CLOSE_', price_shift=0, point=0.01):
    price = pd.Series(price_series(frame, ipc), index=frame.index, dtype=float)
    length1 = int(max(length1, 1))
    length_x = int(max(length1 // 2, 1))
    length_r = int(max(math.sqrt(length1), 1))
    line_full = smooth_series(price, ma_method1, length1)
    line_half = smooth_series(price, ma_method1, length_x)
    line = 2.0 * line_half - line_full
    xline = smooth_series(line, ma_method2, length_r)
    ind = xline + float(point) * float(price_shift)
    color = pd.Series(1.0, index=frame.index)
    delta = ind.diff()
    color = color.where(~(delta > 0), 2.0)
    color = color.where(~(delta < 0), 0.0)
    out = frame.copy()
    out['ind'] = ind
    out['color'] = color
    return out.dropna(subset=['ind', 'color'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class SlopeDirectionLineFeed(bt.feeds.PandasData):
    lines = ('ind', 'color')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('ind', 6), ('color', 7),
    )


class SlopeDirectionLineStrategy(bt.Strategy):
    params = dict(
        mm=0.1,
        mm_mode='LOT',
        stop_loss=1000,
        take_profit=2000,
        deviation=10,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        ma_method1='MODE_LWMA',
        length1=12,
        phase1=15,
        ma_method2='MODE_SMA',
        phase2=15,
        ipc='PRICE_CLOSE_',
        signal_bar=1,
        price_shift=0,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.signal = self.datas[1]
        self.ind = self.signal.ind
        self.color = self.signal.color

        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.order = None
        self.pending_target = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None

        length_r = int(max(math.sqrt(max(int(self.p.length1), 1)), 1))
        self.min_signal_bars = int(self.p.length1) + length_r + max(int(self.p.signal_bar), 1) + 5

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _reset_risk(self):
        self.stop_price = None
        self.take_profit_price = None

    def _set_risk_prices(self):
        if not self.position:
            self._reset_risk()
            return
        price = float(self.position.price)
        unit = self._trade_unit()
        if self.position.size > 0:
            self.stop_price = round(price - self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        if len(self.signal) < self.min_signal_bars:
            return False
        try:
            values = [float(self.color[-idx]), float(self.color[-(idx + 1)]), float(self.ind[-idx]), float(self.ind[-(idx + 1)])]
        except (TypeError, ValueError, IndexError):
            return False
        return not any(np.isnan(v) for v in values)

    def _manage_risk(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.m15.high[0])
        low = float(self.m15.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log('close long stop={0:.2f}'.format(self.stop_price))
                self.pending_target = 0.0
                self.order = self.order_target_size(target=0.0)
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.log('close long target={0:.2f}'.format(self.take_profit_price))
                self.pending_target = 0.0
                self.order = self.order_target_size(target=0.0)
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log('close short stop={0:.2f}'.format(self.stop_price))
                self.pending_target = 0.0
                self.order = self.order_target_size(target=0.0)
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.log('close short target={0:.2f}'.format(self.take_profit_price))
                self.pending_target = 0.0
                self.order = self.order_target_size(target=0.0)
                return True
        return False

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        color_curr = int(round(float(self.color[-idx])))
        color_prev = int(round(float(self.color[-(idx + 1)])))
        ind_curr = float(self.ind[-idx])
        ind_prev = float(self.ind[-(idx + 1)])
        buy_open = sell_open = buy_close = sell_close = False
        if color_curr == 2:
            if self.p.buy_pos_open and color_prev != 2:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True
        if color_curr == 0:
            if self.p.sell_pos_open and color_prev != 0:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True
        return buy_open, buy_close, sell_open, sell_close, color_prev, color_curr, ind_prev, ind_curr

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return
        signal_idx = max(int(self.p.signal_bar), 1)
        signal_dt = bt.num2date(self.signal.datetime[-signal_idx])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        buy_open, buy_close, sell_open, sell_close, color_prev, color_curr, ind_prev, ind_curr = self._evaluate_signals()
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        self.log('sdl color_prev={0} color_curr={1} ind_prev={2:.5f} ind_curr={3:.5f} buy_open={4} sell_open={5}'.format(color_prev, color_curr, ind_prev, ind_curr, buy_open, sell_open))

        target = None
        if buy_open:
            target = float(self.p.size)
        elif sell_open:
            target = -float(self.p.size)
        elif buy_close and self.position.size > 0:
            target = 0.0
        elif sell_close and self.position.size < 0:
            target = 0.0

        if target is None:
            return
        if self.position.size == target:
            return
        self.pending_target = target
        self.order = self.order_target_size(target=target)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.pending_target is not None:
                if self.pending_target > 0 and order.executed.size > 0:
                    self.buy_count += 1
                if self.pending_target < 0 and order.executed.size < 0:
                    self.sell_count += 1
            if self.position:
                self._set_risk_prices()
            else:
                self._reset_risk()
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None
            self.pending_target = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
