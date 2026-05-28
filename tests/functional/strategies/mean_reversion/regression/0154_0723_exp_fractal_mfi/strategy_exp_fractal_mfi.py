from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


PRICE_MAP = {
    'close': lambda row: row['close'],
    'open': lambda row: row['open'],
    'high': lambda row: row['high'],
    'low': lambda row: row['low'],
    'median': lambda row: (row['high'] + row['low']) / 2.0,
    'typical': lambda row: (row['high'] + row['low'] + row['close']) / 3.0,
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
    df['volume'] = df['tick_volume']
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'tick_volume', 'real_volume', 'openinterest']]
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
        'volume': 'sum',
        'tick_volume': 'sum',
        'real_volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def compute_fractal_mfi(frame, e_period=30, normal_speed=30, price_type='typical', volume_type='tick'):
    work = frame.copy()
    price_getter = PRICE_MAP.get(price_type, PRICE_MAP['typical'])
    work['input_price'] = work.apply(price_getter, axis=1)
    volume_col = 'tick_volume' if volume_type == 'tick' else 'real_volume'
    values = []
    prices = work['input_price'].tolist()
    volumes = work[volume_col].tolist()
    for index in range(len(work)):
        if index < e_period + 2:
            values.append(float('nan'))
            continue
        highest = max(prices[index - e_period + 1:index + 1])
        lowest = min(prices[index - e_period + 1:index + 1])
        length = highest - lowest if highest != lowest else 1e-9
        diff = abs(prices[index] - prices[index - e_period]) if index >= e_period else 0.0
        prior_diff = abs(prices[index - 1] - prices[index - e_period - 1]) if index >= e_period + 1 else diff
        hurst = (diff / length) if length else 0.5
        hurst = max(hurst, 1e-6)
        trail_dim = 1.0 / hurst
        beta = trail_dim / 2.0
        speed = max(1, int(round(normal_speed * beta)))
        positive_mf = 0.0
        negative_mf = 0.0
        current_tp = prices[index]
        for k in range(1, speed + 1):
            pos = max(0, index - k)
            previous_tp = prices[pos]
            vol = volumes[max(0, pos - 1)]
            if current_tp > previous_tp:
                positive_mf += vol * current_tp
            if current_tp < previous_tp:
                negative_mf += vol * current_tp
            current_tp = previous_tp
        if negative_mf:
            mfi = 100.0 - 100.0 / (1.0 + positive_mf / negative_mf)
        else:
            mfi = 100.0
        values.append(mfi)
    work['fractal_mfi'] = values
    return work.dropna(subset=['fractal_mfi'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class FractalMfiFeed(bt.feeds.PandasData):
    lines = ('fractal_mfi',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('fractal_mfi', 6),
    )


class ExpFractalMFIStrategy(bt.Strategy):
    params = dict(
        stop_loss=1000,
        take_profit=2000,
        lot=0.1,
        high_level=70.0,
        low_level=30.0,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.ind = self.datas[1]

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

    def _set_risk(self, side, price=None):
        unit = self._unit()
        if price is None:
            price = float(self.base.close[0])
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None

    def _signals(self):
        prev_val = float(self.ind.fractal_mfi[-1])
        curr_val = float(self.ind.fractal_mfi[0])
        buy_open = curr_val > float(self.p.low_level) and prev_val <= float(self.p.low_level)
        sell_open = curr_val < float(self.p.high_level) and prev_val >= float(self.p.high_level)
        buy_close = sell_open
        sell_close = buy_open
        return buy_open, sell_open, buy_close, sell_close

    def _manage_position(self, buy_close, sell_close):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if buy_close:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
        else:
            if sell_close:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.ind) < 2:
            return
        if self.order is not None:
            return
        signal_dt = bt.num2date(self.ind.datetime[0])
        buy_open, sell_open, buy_close, sell_close = self._signals()
        if self.position:
            self._manage_position(buy_close, sell_close)
            return
        if self.last_signal_dt == signal_dt:
            return
        if buy_open:
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.lot)
            self.last_signal_dt = signal_dt
            return
        if sell_open:
            self.signal_count += 1
            self._set_risk('sell')
            self.order = self.sell(size=self.p.lot)
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
