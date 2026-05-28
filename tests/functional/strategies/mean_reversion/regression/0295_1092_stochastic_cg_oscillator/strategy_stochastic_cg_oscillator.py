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


def _recount_positions(max1, max2, count_state):
    count_state -= 1
    if count_state < 0:
        count_state = max1
    positions = []
    for idx in range(max2):
        numb = idx + count_state
        if numb > max1:
            numb -= max2
        positions.append(numb)
    return positions, count_state


def compute_stochastic_cg_oscillator(frame, length=10):
    length = max(int(length), 1)
    hl2 = ((frame['high'] + frame['low']) / 2.0).to_numpy(dtype=float)
    cg_shift = (length + 1.0) / 2.0
    stocg = np.full(len(frame), np.nan, dtype=float)
    trigger = np.full(len(frame), np.nan, dtype=float)

    price_ring = np.zeros(length, dtype=float)
    cg_ring = np.zeros(length, dtype=float)
    value1_ring = np.zeros(4, dtype=float)
    count1 = list(range(length))
    count2 = list(range(4))
    count1_state = 1
    count2_state = 1

    first = 3
    for bar in range(first, len(frame)):
        price_ring[count1[0]] = hl2[bar]

        if bar < length:
            count1, count1_state = _recount_positions(length - 1, length, count1_state)
            count2, count2_state = _recount_positions(3, 4, count2_state)
            continue

        numerator = 0.0
        denominator = 0.0
        for idx in range(length):
            numerator += (1.0 + idx) * price_ring[count1[idx]]
            denominator += price_ring[count1[idx]]

        if denominator != 0.0:
            cg_ring[count1[0]] = -numerator / denominator + cg_shift
        else:
            cg_ring[count1[0]] = 0.0

        hh = cg_ring[count1[0]]
        ll = cg_ring[count1[0]]
        for idx in range(length):
            tmp = cg_ring[count1[idx]]
            hh = max(hh, tmp)
            ll = min(ll, tmp)

        if hh != ll:
            value1_ring[count2[0]] = (cg_ring[count1[0]] - ll) / (hh - ll)
        else:
            value1_ring[count2[0]] = 0.0

        stocg[bar] = (
            4.0 * value1_ring[count2[0]]
            + 3.0 * value1_ring[count2[1]]
            + 2.0 * value1_ring[count2[2]]
            + value1_ring[count2[3]]
        ) / 10.0
        stocg[bar] = 2.0 * (stocg[bar] - 0.5)

        if bar > 0 and not np.isnan(stocg[bar - 1]):
            trigger[bar] = 0.96 * (stocg[bar - 1] + 0.02)

        if bar < len(frame) - 1:
            count1, count1_state = _recount_positions(length - 1, length, count1_state)
            count2, count2_state = _recount_positions(3, 4, count2_state)

    out = frame.copy()
    out['stocg'] = stocg
    out['trigger'] = trigger
    return out.dropna(subset=['stocg', 'trigger'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class StochasticCGFeed(bt.feeds.PandasData):
    lines = ('stocg', 'trigger')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('stocg', 6), ('trigger', 7),
    )


class StochasticCGOscillatorStrategy(bt.Strategy):
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
        self.stocg = self.h8.stocg
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
        self.min_signal_bars = int(self.p.length + 3 + 3 + max(int(self.p.signal_bar), 1))

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _enough_history(self):
        if len(self.h8) < self.min_signal_bars:
            return False
        idx = max(int(self.p.signal_bar), 1)
        needed = [self.stocg[-idx], self.stocg[-idx - 1], self.trigger[-idx], self.trigger[-idx - 1]]
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
        ind_now = float(self.stocg[-idx])
        ind_prev = float(self.stocg[-idx - 1])
        sign_now = float(self.trigger[-idx])
        sign_prev = float(self.trigger[-idx - 1])

        buy_open = buy_close = sell_open = sell_close = False

        if ind_prev > sign_prev:
            if self.p.buy_pos_open and ind_now <= sign_now:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True

        if ind_prev < sign_prev:
            if self.p.sell_pos_open and ind_now >= sign_now:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True

        return buy_open, buy_close, sell_open, sell_close, ind_now, sign_now, ind_prev, sign_prev

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

        buy_open, buy_close, sell_open, sell_close, ind_now, sign_now, ind_prev, sign_prev = self._evaluate_signals()
        self.log('stochastic-cg prev={0:.4f}/{1:.4f} now={2:.4f}/{3:.4f} buy_open={4} sell_open={5}'.format(ind_prev, sign_prev, ind_now, sign_now, buy_open, sell_open))

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
