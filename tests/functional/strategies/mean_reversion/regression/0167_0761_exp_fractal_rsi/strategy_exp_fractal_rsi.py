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
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'openinterest']]
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
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    out['volume'] = out['tick_volume']
    return out


def price_series(frame, applied_price='PRICE_CLOSE_'):
    if applied_price == 'PRICE_OPEN_':
        return frame['open']
    if applied_price == 'PRICE_HIGH_':
        return frame['high']
    if applied_price == 'PRICE_LOW_':
        return frame['low']
    if applied_price == 'PRICE_MEDIAN_':
        return (frame['high'] + frame['low']) / 2.0
    if applied_price == 'PRICE_TYPICAL_':
        return (frame['high'] + frame['low'] + frame['close']) / 3.0
    if applied_price == 'PRICE_WEIGHTED_':
        return (frame['high'] + frame['low'] + 2.0 * frame['close']) / 4.0
    return frame['close']


def compute_fractal_rsi(frame, e_period=30, normal_speed=30, applied_price='PRICE_CLOSE_'):
    src = price_series(frame, applied_price).astype(float).reset_index(drop=True)
    values = src.to_numpy(dtype=float)
    n = len(values)
    result = np.full(n, np.nan, dtype=float)
    prev_fdi = np.nan
    g_period_minus_1 = max(int(e_period) - 1, 1)
    log_2 = math.log(2.0)
    start = max(int(e_period), int(normal_speed))

    for index in range(start, n):
        window = values[index - int(e_period) + 1:index + 1]
        if len(window) < int(e_period):
            continue
        price_max = np.max(window)
        price_min = np.min(window)
        length = 0.0
        prior_diff = 0.0
        if price_max - price_min > 0.0:
            for k in range(g_period_minus_1 + 1):
                diff = (values[index - k] - price_min) / (price_max - price_min)
                if k > 0:
                    length += math.sqrt((diff - prior_diff) ** 2 + (1.0 / (int(e_period) ** 2)))
                prior_diff = diff
        if length > 0.0:
            fdi = 1.0 + (math.log(length) + log_2) / math.log(2.0 * g_period_minus_1)
            prev_fdi = fdi
        else:
            fdi = prev_fdi
        if np.isnan(fdi):
            continue
        hurst = 2.0 - fdi
        if hurst == 0:
            continue
        trail_dim = 1.0 / hurst
        beta = trail_dim / 2.0
        speed = max(int(round(int(normal_speed) * beta)), 1)
        if index < speed:
            continue
        diffs = np.diff(values[index - speed:index + 1])
        pos = np.clip(diffs, 0, None).sum() / speed
        neg = np.clip(-diffs, 0, None).sum() / speed
        if neg > 0:
            rsi = 100.0 - (100.0 / (1.0 + pos / neg))
        elif pos > 0:
            rsi = 100.0
        else:
            rsi = 50.0
        result[index] = rsi

    out = frame.copy()
    out['fractal_rsi'] = result
    out = out.dropna(subset=['fractal_rsi'])
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class FractalRsiFeed(bt.feeds.PandasData):
    lines = ('fractal_rsi',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('fractal_rsi', 6),
    )


class ExpFractalRsiStrategy(bt.Strategy):
    params = dict(
        signal_tf_minutes=240,
        trend='DIRECT',
        e_period=30,
        normal_speed=30,
        applied_price='PRICE_CLOSE_',
        high_level=60,
        low_level=40,
        signal_bar=1,
        stop_loss=1000,
        take_profit=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        size=0.1,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
        self.frsi = self.signal.fractal_rsi

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.order = None
        self.last_signal_dt = None
        self.stop_price = None
        self.take_profit_price = None

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _set_risk(self, side):
        price = float(self.base.close[0])
        unit = self._unit()
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        try:
            _ = float(self.frsi[-idx])
            _ = float(self.frsi[-(idx + 1)])
            return True
        except (IndexError, TypeError, ValueError):
            return False

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        curr = float(self.frsi[-idx])
        prev = float(self.frsi[-(idx + 1)])
        buy_open = buy_close = sell_open = sell_close = False
        direct = str(self.p.trend).upper() == 'DIRECT'
        if direct:
            if prev > float(self.p.low_level) and curr <= float(self.p.low_level):
                if self.p.buy_pos_open:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
            if prev < float(self.p.high_level) and curr >= float(self.p.high_level):
                if self.p.sell_pos_open:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
        else:
            if prev > float(self.p.low_level) and curr <= float(self.p.low_level):
                if self.p.sell_pos_open:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
            if prev < float(self.p.high_level) and curr >= float(self.p.high_level):
                if self.p.buy_pos_open:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
        return buy_open, buy_close, sell_open, sell_close, prev, curr

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self._manage_risk():
            return
        if not self._enough_history():
            return
        idx = max(int(self.p.signal_bar), 1)
        signal_dt = bt.num2date(self.signal.datetime[-idx])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        buy_open, buy_close, sell_open, sell_close, prev, curr = self._evaluate_signals()
        if buy_open or sell_open:
            self.signal_count += 1
        self.log(f'fractal_rsi prev={prev:.2f} curr={curr:.2f} buy_open={buy_open} sell_open={sell_open}')
        if buy_close and self.position and self.position.size > 0:
            self.order = self.close()
            return
        if sell_close and self.position and self.position.size < 0:
            self.order = self.close()
            return
        if buy_open and (not self.position or self.position.size <= 0):
            if self.position and self.position.size < 0:
                self.order = self.close()
                return
            self._set_risk('buy')
            self.order = self.buy(size=self.p.size)
            return
        if sell_open and (not self.position or self.position.size >= 0):
            if self.position and self.position.size > 0:
                self.order = self.close()
                return
            self._set_risk('sell')
            self.order = self.sell(size=self.p.size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
