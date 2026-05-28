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


def compute_fisher_cg_oscillator(frame, length=10):
    length = max(int(length), 1)
    hl2 = ((frame['high'] + frame['low']) / 2.0).to_numpy(dtype=float)
    cg_shift = (length + 1.0) / 2.0
    cg = np.full(len(frame), np.nan, dtype=float)
    value1 = np.full(len(frame), np.nan, dtype=float)
    fcg = np.full(len(frame), np.nan, dtype=float)
    trigger = np.full(len(frame), np.nan, dtype=float)

    for bar in range(length - 1, len(frame)):
        numerator = 0.0
        denominator = 0.0
        for count in range(length):
            price = hl2[bar - count]
            numerator += (1.0 + count) * price
            denominator += price
        cg[bar] = (-numerator / denominator + cg_shift) if denominator != 0.0 else 0.0

        cg_window = cg[max(0, bar - length + 1): bar + 1]
        cg_window = cg_window[~np.isnan(cg_window)]
        if cg_window.size == 0:
            continue
        hh = np.max(cg_window)
        ll = np.min(cg_window)
        value1[bar] = (cg[bar] - ll) / (hh - ll) if hh != ll else 0.0

        if bar < length - 1 + 3:
            continue
        v0 = value1[bar]
        v1 = value1[bar - 1]
        v2 = value1[bar - 2]
        v3 = value1[bar - 3]
        if any(np.isnan(v) for v in [v0, v1, v2, v3]):
            continue
        value2 = (4.0 * v0 + 3.0 * v1 + 2.0 * v2 + v3) / 10.0
        scaled = 1.98 * (value2 - 0.5)
        scaled = min(max(scaled, -0.999999), 0.999999)
        fcg[bar] = 0.5 * math.log((1.0 + scaled) / (1.0 - scaled))
        if bar > 0 and not np.isnan(fcg[bar - 1]):
            trigger[bar] = fcg[bar - 1]

    out = frame.copy()
    out['fcg'] = fcg
    out['trigger'] = trigger
    return out.dropna(subset=['fcg', 'trigger'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class FisherCGFeed(bt.feeds.PandasData):
    lines = ('fcg', 'trigger')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('fcg', 6), ('trigger', 7),
    )


class FisherCGOscillatorStrategy(bt.Strategy):
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
        length=10,
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h8 = self.datas[1]
        self.fcg = self.h8.fcg
        self.trigger = self.h8.trigger

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.current_side = None
        self.last_signal_dt = None

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        needed = [self.fcg[-idx], self.fcg[-idx - 1], self.trigger[-idx], self.trigger[-idx - 1]]
        return not any(math.isnan(float(v)) for v in needed)

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
        self.current_side = side

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        fcg_now = float(self.fcg[-idx])
        fcg_prev = float(self.fcg[-idx - 1])
        trig_now = float(self.trigger[-idx])
        trig_prev = float(self.trigger[-idx - 1])

        buy_open = buy_close = sell_open = sell_close = False
        if fcg_now > trig_now and fcg_prev <= trig_prev:
            if self.p.buy_pos_open:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if fcg_now < trig_now and fcg_prev >= trig_prev:
            if self.p.sell_pos_open:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        return buy_open, buy_close, sell_open, sell_close, fcg_now, trig_now, fcg_prev, trig_prev

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return

        signal_dt = bt.num2date(self.h8.datetime[-max(int(self.p.signal_bar), 1)])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        buy_open, buy_close, sell_open, sell_close, fcg_now, trig_now, fcg_prev, trig_prev = self._evaluate_signals()
        self.log('fcg prev={0:.4f}/{1:.4f} now={2:.4f}/{3:.4f} buy_open={4} sell_open={5}'.format(fcg_prev, trig_prev, fcg_now, trig_now, buy_open, sell_open))

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
                self.current_side = None
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
