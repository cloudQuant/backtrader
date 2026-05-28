from __future__ import absolute_import, division, print_function, unicode_literals

import io

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
    mapping = str(applied_price).upper()
    if mapping == 'PRICE_OPEN_':
        return frame['open']
    if mapping == 'PRICE_HIGH_':
        return frame['high']
    if mapping == 'PRICE_LOW_':
        return frame['low']
    if mapping == 'PRICE_MEDIAN_':
        return (frame['high'] + frame['low']) / 2.0
    if mapping == 'PRICE_TYPICAL_':
        return (frame['high'] + frame['low'] + frame['close']) / 3.0
    if mapping == 'PRICE_WEIGHTED_':
        return (frame['high'] + frame['low'] + 2.0 * frame['close']) / 4.0
    return frame['close']


def _highest(values, n, index):
    return np.max(values[index - n + 1:index + 1])


def _lowest(values, n, index):
    return np.min(values[index - n + 1:index + 1])


def compute_fractal_wpr(frame, e_period=30, normal_speed=30, applied_price='PRICE_CLOSE_'):
    out = frame.copy()
    close_like = price_series(out, applied_price).to_numpy(dtype=float)
    high = out['high'].to_numpy(dtype=float)
    low = out['low'].to_numpy(dtype=float)
    rates_total = len(out)
    values = np.full(rates_total, np.nan, dtype=float)
    start = int(max(e_period, normal_speed))
    wpr_prev = -50.0
    for index in range(start, rates_total):
        diff = max(high[index - e_period + 1:index + 1]) - min(low[index - e_period + 1:index + 1])
        prior_diff = max(high[index - e_period:index]) - min(low[index - e_period:index]) if index - e_period >= 0 else diff
        if prior_diff == 0 or diff == 0:
            trail_dim = 1.0
        else:
            ratio = diff / prior_diff if prior_diff else 1.0
            hurst = np.clip(ratio, 0.1, 10.0)
            trail_dim = 1.0 / hurst
        beta = trail_dim / 2.0
        speed = max(2, int(round(normal_speed * beta)))
        if index < speed:
            continue
        max_high = _highest(high, speed, index)
        min_low = _lowest(low, speed, index)
        spread = max_high - min_low
        if spread != 0:
            wpr = -(max_high - close_like[index]) * 100.0 / spread
        else:
            wpr = wpr_prev
        values[index] = wpr
        if index != rates_total - 1:
            wpr_prev = wpr
    out['fractal_wpr'] = values
    return out.dropna(subset=['fractal_wpr'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class FractalWPRFeed(bt.feeds.PandasData):
    lines = ('fractal_wpr',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('fractal_wpr', 6),
    )


class ExpFractalWPRStrategy(bt.Strategy):
    params = dict(
        stop_loss=1000,
        take_profit=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        trend='DIRECT',
        high_level=-30,
        low_level=-70,
        signal_bar=1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        size=0.1,
        e_period=30,
        normal_speed=30,
        applied_price='PRICE_CLOSE_',
    )

    def __init__(self):
        self.base = self.datas[0]
        self.ind = self.datas[1]
        self.fwpr = self.ind.fractal_wpr

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

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _set_risk(self, side):
        unit = self._unit()
        price = float(self.base.close[0])
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits))
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits))

    def _manage_risk(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if low <= self.stop_price or high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if high >= self.stop_price or low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self._manage_risk():
            return
        idx = max(int(self.p.signal_bar), 1)
        try:
            prev_val = float(self.fwpr[-idx - 1])
            curr_val = float(self.fwpr[-idx])
        except (IndexError, TypeError, ValueError):
            return
        signal_dt = bt.num2date(self.ind.datetime[-idx])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        buy_open = buy_close = sell_open = sell_close = False
        direct = str(self.p.trend).upper() == 'DIRECT'
        if direct:
            if prev_val > float(self.p.low_level) and curr_val <= float(self.p.low_level):
                if self.p.buy_pos_open:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
            if prev_val < float(self.p.high_level) and curr_val >= float(self.p.high_level):
                if self.p.sell_pos_open:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
        else:
            if prev_val > float(self.p.low_level) and curr_val <= float(self.p.low_level):
                if self.p.sell_pos_open:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
            if prev_val < float(self.p.high_level) and curr_val >= float(self.p.high_level):
                if self.p.buy_pos_open:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
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
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.size)
            return
        if sell_open and (not self.position or self.position.size >= 0):
            if self.position and self.position.size > 0:
                self.order = self.close()
                return
            self.signal_count += 1
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
