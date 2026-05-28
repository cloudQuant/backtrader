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


def compute_range_expansion_index(frame, rei_period=8):
    rei_period = max(int(rei_period), 1)
    high = frame['high'].to_numpy(dtype=float)
    low = frame['low'].to_numpy(dtype=float)
    close = frame['close'].to_numpy(dtype=float)
    rei = np.full(len(frame), np.nan, dtype=float)
    color = np.full(len(frame), np.nan, dtype=float)

    def sub_value(i):
        diff1 = high[i] - high[i - 2]
        diff2 = low[i] - low[i - 2]
        num_zero1 = 0 if (high[i - 2] < close[i - 7] and high[i - 2] < close[i - 8] and high[i] < high[i - 5] and high[i] < high[i - 6]) else 1
        num_zero2 = 0 if (low[i - 2] > close[i - 7] and low[i - 2] > close[i - 8] and low[i] > low[i - 5] and low[i] > low[i - 6]) else 1
        return diff1 * num_zero1 + diff2 * num_zero2

    def abs_value(i):
        return abs(high[i] - high[i - 2]) + abs(low[i] - low[i - 2])

    min_rates_total = rei_period + 8
    for bar in range(min_rates_total - 1, len(frame)):
        sub_sum = 0.0
        abs_sum = 0.0
        for iii in range(rei_period):
            idx = bar - iii
            sub_sum += sub_value(idx)
            abs_sum += abs_value(idx)
        rei[bar] = (sub_sum / abs_sum * 100.0) if abs_sum != 0.0 else 0.0

    for bar in range(min_rates_total, len(frame)):
        color[bar] = 0.0
        if rei[bar] > 0:
            if rei[bar] > rei[bar - 1]:
                color[bar] = 1.0
            elif rei[bar] < rei[bar - 1]:
                color[bar] = 2.0
        elif rei[bar] < 0:
            if rei[bar] < rei[bar - 1]:
                color[bar] = 3.0
            elif rei[bar] > rei[bar - 1]:
                color[bar] = 4.0

    out = frame.copy()
    out['rei'] = rei
    out['rei_color'] = color
    return out.dropna(subset=['rei'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class RangeExpansionIndexFeed(bt.feeds.PandasData):
    lines = ('rei', 'rei_color')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('rei', 6), ('rei_color', 7),
    )


class RangeExpansionIndexStrategy(bt.Strategy):
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
        rei_period=8,
        up_indicator_level=60,
        dn_indicator_level=-60,
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h8 = self.datas[1]
        self.rei = self.h8.rei

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

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        try:
            values = [float(self.rei[-idx]), float(self.rei[-(idx + 1)])]
        except (TypeError, ValueError, IndexError):
            return False
        return not any(math.isnan(v) for v in values)

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
        rei_now = float(self.rei[-idx])
        rei_prev = float(self.rei[-(idx + 1)])

        buy_open = buy_close = sell_open = sell_close = False
        if rei_prev > self.p.dn_indicator_level:
            if self.p.buy_pos_open and rei_now <= self.p.dn_indicator_level:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        else:
            buy_close = True

        if rei_prev < self.p.up_indicator_level:
            if self.p.sell_pos_open and rei_now >= self.p.up_indicator_level:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        else:
            sell_close = True

        return buy_open, buy_close, sell_open, sell_close, rei_prev, rei_now

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

        buy_open, buy_close, sell_open, sell_close, rei_prev, rei_now = self._evaluate_signals()
        self.log('rei prev={0:.2f} now={1:.2f} buy_open={2} sell_open={3}'.format(rei_prev, rei_now, buy_open, sell_open))

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
