from __future__ import absolute_import, division, print_function, unicode_literals

import io
from collections import deque

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


def smooth_series(series, period, method='MODE_SMA'):
    period = max(int(period), 1)
    if method == 'MODE_EMA':
        return series.ewm(span=period, adjust=False).mean()
    if method == 'MODE_SMMA':
        return series.ewm(alpha=1.0 / period, adjust=False).mean()
    if method == 'MODE_LWMA':
        weights = np.arange(1, period + 1, dtype=float)
        return series.rolling(period, min_periods=period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)
    return series.rolling(period, min_periods=period).mean()


def compute_jbraintrend1stop(frame, atr_period=7, sto_period=9, ma_method='MODE_SMA', stop_dperiod=3, length_=7, point=0.01):
    out = frame.copy()
    d = 2.3
    s = 1.5
    x1 = 53.0
    x2 = 47.0
    ma = ma_method or 'MODE_SMA'
    tr_components = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low'] - out['close'].shift(1)).abs(),
    ], axis=1)
    true_range = tr_components.max(axis=1)
    atr = true_range.rolling(atr_period, min_periods=atr_period).mean()
    atr1 = true_range.rolling(atr_period + stop_dperiod, min_periods=atr_period + stop_dperiod).mean()
    highest = out['high'].rolling(sto_period, min_periods=sto_period).max()
    lowest = out['low'].rolling(sto_period, min_periods=sto_period).min()
    denom = highest - lowest
    stochastic = pd.Series(np.where(denom == 0, 50.0, 100.0 * (out['close'] - lowest) / denom), index=out.index)
    jh = smooth_series(out['high'], length_, ma)
    jl = smooth_series(out['low'], length_, ma)
    jc = smooth_series(out['close'], length_, ma)
    buy_stop = pd.Series(0.0, index=out.index)
    sell_stop = pd.Series(0.0, index=out.index)
    buy_stop_line = pd.Series(0.0, index=out.index)
    sell_stop_line = pd.Series(0.0, index=out.index)
    p_state = 0
    r_state = 0.0
    start = max(atr_period + stop_dperiod, sto_period, length_, 30) + 2
    for i in range(start, len(out)):
        range_value = atr.iloc[i] / d if pd.notna(atr.iloc[i]) else np.nan
        range1 = atr1.iloc[i] * s if pd.notna(atr1.iloc[i]) else np.nan
        if pd.isna(range_value) or pd.isna(range1) or pd.isna(stochastic.iloc[i]) or pd.isna(jh.iloc[i]) or pd.isna(jl.iloc[i]) or pd.isna(jc.iloc[i]) or pd.isna(jc.iloc[i - 2]):
            continue
        val1 = 0.0
        val2 = 0.0
        val3 = abs(round(float(jc.iloc[i]), 8) - round(float(jc.iloc[i - 2]), 8))
        if val3 > range_value:
            if stochastic.iloc[i] < x2 and p_state != 1:
                value3 = float(jh.iloc[i]) + range1 / 4.0
                val1 = value3
                p_state = 1
                r_state = val1
                sell_stop.iloc[i] = val1
                sell_stop_line.iloc[i] = val1
            if stochastic.iloc[i] > x1 and p_state != 2:
                value3 = float(jl.iloc[i]) - range1 / 4.0
                val2 = value3
                p_state = 2
                r_state = val2
                buy_stop.iloc[i] = val2
                buy_stop_line.iloc[i] = val2
        value4 = float(jh.iloc[i]) + range1
        value5 = float(jl.iloc[i]) - range1
        if val1 == 0.0 and val2 == 0.0:
            if p_state == 1:
                if value4 < r_state:
                    r_state = value4
                sell_stop.iloc[i] = r_state
                sell_stop_line.iloc[i] = r_state
            if p_state == 2:
                if value5 > r_state:
                    r_state = value5
                buy_stop.iloc[i] = r_state
                buy_stop_line.iloc[i] = r_state
    out['sell_stop'] = sell_stop
    out['buy_stop'] = buy_stop
    out['sell_stop_line'] = sell_stop_line
    out['buy_stop_line'] = buy_stop_line
    out = out[(out['sell_stop'] != 0.0) | (out['buy_stop'] != 0.0) | (out['sell_stop_line'] != 0.0) | (out['buy_stop_line'] != 0.0)]
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5),
    )


class JBrainTrend1StopFeed(bt.feeds.PandasData):
    lines = ('sell_stop', 'buy_stop', 'sell_stop_line', 'buy_stop_line',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('sell_stop', 6), ('buy_stop', 7), ('sell_stop_line', 8), ('buy_stop_line', 9),
    )


class JBrainTrend1StopStrategy(bt.Strategy):
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
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        atr_period=7,
        sto_period=9,
        ma_method='MODE_SMA',
        stop_dperiod=3,
        length_=7,
        phase_=100,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.signal = self.datas[1]
        self.sell_stop = self.signal.sell_stop
        self.buy_stop = self.signal.buy_stop

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

        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _set_risk_prices(self, side):
        price = float(self.m15.close[0])
        unit = self._trade_unit()
        if side == 'buy':
            self.stop_price = round(price - self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.m15.high[0])
        low = float(self.m15.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.entry_order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.entry_order = self.close()
                return True
        return False

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        try:
            _ = float(self.buy_stop[-idx])
            _ = float(self.buy_stop[-(idx + 1)])
            _ = float(self.sell_stop[-idx])
            _ = float(self.sell_stop[-(idx + 1)])
            return True
        except (TypeError, ValueError, IndexError):
            return False

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        up_curr = float(self.buy_stop[-idx])
        up_prev = float(self.buy_stop[-(idx + 1)])
        dn_curr = float(self.sell_stop[-idx])
        dn_prev = float(self.sell_stop[-(idx + 1)])
        buy_open = sell_open = buy_close = sell_close = False
        if up_curr != 0.0:
            if self.p.buy_pos_open and dn_prev != 0.0:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True
        if dn_curr != 0.0:
            if self.p.sell_pos_open and up_prev != 0.0:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True
        debug = 'buy_stop_curr={0:.5f} buy_stop_prev={1:.5f} sell_stop_curr={2:.5f} sell_stop_prev={3:.5f}'.format(up_curr, up_prev, dn_curr, dn_prev)
        return buy_open, buy_close, sell_open, sell_close, debug

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
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
        buy_open, buy_close, sell_open, sell_close, debug = self._evaluate_signals()
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        self.log('jbraintrend1stop {0} buy_open={1} sell_open={2}'.format(debug, buy_open, sell_open))
        if buy_close and self.position and self.position.size > 0:
            self.entry_order = self.close()
            return
        if sell_close and self.position and self.position.size < 0:
            self.entry_order = self.close()
            return
        if buy_open and (not self.position or self.position.size <= 0):
            if self.position and self.position.size < 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('buy')
            self.entry_order = self.buy(size=self.p.size)
            return
        if sell_open and (not self.position or self.position.size >= 0):
            if self.position and self.position.size > 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('sell')
            self.entry_order = self.sell(size=self.p.size)

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
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
