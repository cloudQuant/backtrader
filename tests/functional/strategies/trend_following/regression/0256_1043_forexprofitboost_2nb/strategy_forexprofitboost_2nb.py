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


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum', 'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def moving_average(series, period, ma_type):
    ma_type = str(ma_type).upper()
    period = int(period)
    if ma_type == 'EMA':
        return series.ewm(span=period, adjust=False).mean()
    if ma_type == 'SMA':
        return series.rolling(period).mean()
    raise ValueError('Unsupported MA type: {0}'.format(ma_type))


def bollinger_bands(series, period, deviation):
    mid = series.rolling(int(period)).mean()
    std = series.rolling(int(period)).std(ddof=0)
    upper = mid + float(deviation) * std
    lower = mid - float(deviation) * std
    return upper, lower


def compute_forexprofitboost_2nb(frame, ma_period1=7, ma_type1='EMA', ma_price1='CLOSE', ma_period2=21, ma_type2='SMA', ma_price2='CLOSE', bb_period=15, bb_deviation=1.0, bb_shift=1):
    if str(ma_price1).upper() != 'CLOSE' or str(ma_price2).upper() != 'CLOSE':
        raise ValueError('This migration currently reconstructs CLOSE-based MA inputs only')
    close = frame['close']
    ma1 = moving_average(close, ma_period1, ma_type1)
    ma2 = moving_average(close, ma_period2, ma_type2)
    upper, lower = bollinger_bands(close, bb_period, bb_deviation)
    if int(bb_shift) != 0:
        upper = upper.shift(int(bb_shift))
        lower = lower.shift(int(bb_shift))
    up_state = ma1 > ma2
    down_state = ~up_state
    out = frame.copy()
    out['ma1'] = ma1
    out['ma2'] = ma2
    out['bb_upper'] = upper
    out['bb_lower'] = lower
    out['up_state'] = up_state.astype(float)
    out['down_state'] = down_state.astype(float)
    return out.dropna(subset=['ma1', 'ma2', 'bb_upper', 'bb_lower'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class ForexProfitBoostFeed(bt.feeds.PandasData):
    lines = ('up_state', 'down_state')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('up_state', 6), ('down_state', 7),
    )


class ForexProfitBoost2nbStrategy(bt.Strategy):
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
        ma_period1=7,
        ma_type1='EMA',
        ma_price1='CLOSE',
        ma_period2=21,
        ma_type2='SMA',
        ma_price2='CLOSE',
        bb_period=15,
        bb_deviation=1.0,
        bb_shift=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h6 = self.datas[1]
        self.up_state = self.h6.up_state
        self.down_state = self.h6.down_state

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

    def _state(self, line, idx):
        value = float(line[-idx])
        return not math.isnan(value) and value > 0.5

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        try:
            float(self.up_state[-idx])
            float(self.up_state[-(idx + 1)])
            float(self.down_state[-idx])
            float(self.down_state[-(idx + 1)])
        except (TypeError, ValueError, IndexError):
            return False
        return True

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

    def _set_risk_prices(self, side):
        price = float(self.m15.close[0])
        unit = self._trade_unit()
        if side == 'buy':
            self.stop_price = round(price - self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        prev_up = self._state(self.up_state, idx + 1)
        curr_up = self._state(self.up_state, idx)
        prev_dn = self._state(self.down_state, idx + 1)
        curr_dn = self._state(self.down_state, idx)
        buy_open = buy_close = sell_open = sell_close = False
        if prev_up:
            if self.p.buy_pos_open and curr_dn:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if prev_dn:
            if self.p.sell_pos_open and curr_up:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        return buy_open, buy_close, sell_open, sell_close, prev_up, curr_up, prev_dn, curr_dn

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return
        signal_dt = bt.num2date(self.h6.datetime[-max(int(self.p.signal_bar), 1)])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        buy_open, buy_close, sell_open, sell_close, prev_up, curr_up, prev_dn, curr_dn = self._evaluate_signals()
        self.log('forexprofitboost prev_up={0} curr_up={1} prev_dn={2} curr_dn={3} buy_open={4} sell_open={5}'.format(prev_up, curr_up, prev_dn, curr_dn, buy_open, sell_open))
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
