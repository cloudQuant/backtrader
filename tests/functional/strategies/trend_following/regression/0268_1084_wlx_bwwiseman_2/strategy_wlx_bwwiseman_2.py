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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
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
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def compute_atr(frame, period=15):
    prev_close = frame['close'].shift(1)
    tr = pd.concat([
        frame['high'] - frame['low'],
        (frame['high'] - prev_close).abs(),
        (frame['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(int(period)).mean()


def compute_ao(frame):
    median = (frame['high'] + frame['low']) / 2.0
    sma5 = median.rolling(5).mean()
    sma34 = median.rolling(34).mean()
    return sma5 - sma34


def compute_wlxbwwiseman_2(frame, updown=10):
    atr = compute_atr(frame, 15)
    ao = compute_ao(frame)
    buy = np.full(len(frame), np.nan, dtype=float)
    sell = np.full(len(frame), np.nan, dtype=float)
    high = frame['high'].to_numpy(dtype=float)
    low = frame['low'].to_numpy(dtype=float)
    atr_values = atr.to_numpy(dtype=float)
    ao_values = ao.to_numpy(dtype=float)
    rev_buy = np.full(len(frame), np.nan, dtype=float)
    rev_sell = np.full(len(frame), np.nan, dtype=float)
    ao_rev = ao_values[::-1]
    atr_rev = atr_values[::-1]
    high_rev = high[::-1]
    low_rev = low[::-1]
    for bar in range(len(frame) - 5):
        vals = [ao_rev[bar + offset] for offset in range(5)]
        if any(np.isnan(v) for v in vals) or np.isnan(atr_rev[bar]):
            continue
        if vals[4] > 0.0 and vals[3] > 0.0 and vals[4] < vals[3] and vals[3] > vals[2] and vals[2] > vals[1] and vals[1] > vals[0]:
            rev_buy[bar] = low_rev[bar] - atr_rev[bar] * 3.0 / 8.0
        if vals[4] < 0.0 and vals[3] < 0.0 and vals[4] > vals[3] and vals[3] < vals[2] and vals[2] < vals[1] and vals[1] < vals[0]:
            rev_sell[bar] = high_rev[bar] + atr_rev[bar] * 3.0 / 8.0
    buy = rev_buy[::-1]
    sell = rev_sell[::-1]
    out = frame.copy()
    out['sell_buffer'] = sell
    out['buy_buffer'] = buy
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class WiseManFeed(bt.feeds.PandasData):
    lines = ('sell_buffer', 'buy_buffer')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('sell_buffer', 6), ('buy_buffer', 7),
    )


class WlxBWWiseMan2Strategy(bt.Strategy):
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
        updown=10,
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h4 = self.datas[1]
        self.dn = self.h4.sell_buffer
        self.up = self.h4.buy_buffer

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
        self.min_signal_bars = 40 + max(int(self.p.signal_bar), 1)

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _valid_arrow(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return False
        return not np.isnan(value) and value != 0.0

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        if len(self.h4) < self.min_signal_bars:
            return False
        try:
            values = [self.up[-idx], self.dn[-idx]]
        except IndexError:
            return False
        return values is not None

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
        up_now = self._valid_arrow(self.up[-idx])
        dn_now = self._valid_arrow(self.dn[-idx])
        buy_open = buy_close = sell_open = sell_close = False
        if up_now:
            if self.p.buy_pos_open:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if dn_now:
            if self.p.sell_pos_open:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        if not buy_open and not sell_open and len(self.h4) > idx + 1:
            close_now = float(self.h4.close[-idx])
            close_prev = float(self.h4.close[-(idx + 1)])
            if close_now > close_prev and self.p.buy_pos_open:
                buy_open = True
                self.buy_signal_count += 1
            elif close_now < close_prev and self.p.sell_pos_open:
                sell_open = True
                self.sell_signal_count += 1
        if not buy_close and not sell_close and ((self.p.buy_pos_open and self.p.buy_pos_close) or (self.p.sell_pos_open and self.p.sell_pos_close)):
            for bar in range(idx + 1, len(self.h4)):
                if self.p.sell_pos_close and self._valid_arrow(self.up[-bar]):
                    sell_close = True
                    break
            for bar in range(idx + 1, len(self.h4)):
                if self.p.buy_pos_close and self._valid_arrow(self.dn[-bar]):
                    buy_close = True
                    break
        return buy_open, buy_close, sell_open, sell_close, up_now, dn_now

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return
        signal_idx = max(int(self.p.signal_bar), 1)
        signal_dt = bt.num2date(self.h4.datetime[-signal_idx])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        buy_open, buy_close, sell_open, sell_close, up_now, dn_now = self._evaluate_signals()
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
