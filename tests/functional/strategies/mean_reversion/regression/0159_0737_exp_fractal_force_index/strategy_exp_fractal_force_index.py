from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


PRICE_MAP = {
    'close': lambda row: row['close'],
    'open': lambda row: row['open'],
    'high': lambda row: row['high'],
    'low': lambda row: row['low'],
    'median': lambda row: (row['high'] + row['low']) / 2.0,
    'typical': lambda row: (row['high'] + row['low'] + row['close']) / 3.0,
    'weighted': lambda row: (row['high'] + row['low'] + 2.0 * row['close']) / 4.0,
    'simple': lambda row: (row['open'] + row['close']) / 2.0,
    'quarter': lambda row: (row['high'] + row['low'] + row['open'] + row['close']) / 4.0,
}


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
    out['volume'] = out['tick_volume']
    return out


def _sma(values):
    return sum(values) / len(values)


def _ema(values):
    period = len(values)
    ema = values[0]
    smooth = 2.0 / (1.0 + period)
    for value in values[1:]:
        ema = value * smooth + ema * (1.0 - smooth)
    return ema


def _smma(values):
    period = len(values)
    smma = values[0]
    for value in values[1:]:
        smma = (smma * (period - 1) + value) / period
    return smma


def _lwma(values):
    weights = list(range(1, len(values) + 1))
    weighted_sum = sum(v * w for v, w in zip(values, weights))
    return weighted_sum / sum(weights)


def _ma(values, method):
    if method == 'ema':
        return _ema(values)
    if method == 'smma':
        return _smma(values)
    if method == 'lwma':
        return _lwma(values)
    return _sma(values)


def _price_series(frame, price_type):
    getter = PRICE_MAP.get(price_type, PRICE_MAP['close'])
    return frame.apply(getter, axis=1).tolist()


def compute_fractal_force_index(frame, e_period=30, normal_speed=30, ma_method='sma', price_type='close', volume_type='tick'):
    work = frame.copy()
    price_values = _price_series(work, price_type)
    volumes = work['tick_volume'].tolist() if volume_type == 'tick' else work['real_volume'].tolist()
    ffi = [math.nan] * len(work)
    fractal_ma_prev = None
    log_2 = math.log(2.0)
    g_period_minus_1 = e_period - 1
    min_rates_total = int(max(e_period, normal_speed))
    for index in range(len(work)):
        if index < min_rates_total or index < e_period:
            continue
        window = price_values[index - e_period + 1:index + 1]
        price_max = max(window)
        price_min = min(window)
        length = 0.0
        prior_diff = None
        if price_max - price_min > 0.0:
            for value in reversed(window):
                diff = (value - price_min) / (price_max - price_min)
                if prior_diff is not None:
                    length += math.sqrt((diff - prior_diff) ** 2 + (1.0 / (e_period ** 2)))
                prior_diff = diff
        if length <= 0.0:
            continue
        fdi = 1.0 + (math.log(length) + log_2) / math.log(2 * g_period_minus_1)
        hurst = 2.0 - fdi
        if hurst == 0:
            continue
        trail_dim = 1.0 / hurst
        beta = trail_dim / 2.0
        speed = max(1, int(round(normal_speed * beta)))
        if index < speed:
            continue
        ma_window = price_values[index - speed + 1:index + 1]
        fractal_ma = _ma(ma_window, ma_method)
        if fractal_ma_prev is None:
            fractal_ma_prev = fractal_ma
            ffi[index] = 0.0
            continue
        ffi[index] = float(volumes[index]) * (fractal_ma - fractal_ma_prev)
        fractal_ma_prev = fractal_ma
    work['ffi'] = ffi
    return work.dropna(subset=['ffi'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class FractalForceFeed(bt.feeds.PandasData):
    lines = ('ffi',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('ffi', 6),
    )


class ExpFractalForceIndexStrategy(bt.Strategy):
    params = dict(
        stop_loss=1000,
        take_profit=2000,
        lots=0.1,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        trend='direct',
        high_level=0.0,
        low_level=0.0,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.ffi_feed = self.datas[1]

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
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _set_risk(self, side):
        unit = self._unit()
        price = float(self.base.close[0])
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None

    def _ffi_cross_signal(self):
        prev_val = float(self.ffi_feed.ffi[-1])
        curr_val = float(self.ffi_feed.ffi[0])
        high_level = float(self.p.high_level)
        low_level = float(self.p.low_level)
        trend = str(self.p.trend).lower()
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if trend == 'direct':
            if prev_val <= high_level and curr_val > high_level:
                if self.p.buy_pos_open:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
            if prev_val >= low_level and curr_val < low_level:
                if self.p.sell_pos_open:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
        else:
            if prev_val <= high_level and curr_val > high_level:
                if self.p.sell_pos_open:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
            if prev_val >= low_level and curr_val < low_level:
                if self.p.buy_pos_open:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
        return buy_open, sell_open, buy_close, sell_close

    def _manage_position(self, buy_close, sell_close):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if buy_close and self.p.buy_pos_close:
                self.order = self.close()
                return True
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if sell_close and self.p.sell_pos_close:
                self.order = self.close()
                return True
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.ffi_feed) < 2:
            return
        if self.order is not None:
            return
        signal_dt = bt.num2date(self.ffi_feed.datetime[0])
        buy_open, sell_open, buy_close, sell_close = self._ffi_cross_signal()
        if self.position:
            self._manage_position(buy_close, sell_close)
            return
        if self.last_signal_dt == signal_dt:
            return
        if buy_open:
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.lots)
            self.last_signal_dt = signal_dt
            return
        if sell_open:
            self.signal_count += 1
            self._set_risk('sell')
            self.order = self.sell(size=self.p.lots)
            self.last_signal_dt = signal_dt

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
