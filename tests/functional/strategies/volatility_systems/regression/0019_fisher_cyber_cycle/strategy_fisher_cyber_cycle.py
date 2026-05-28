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


def compute_fisher_cyber_cycle(frame, alpha=0.07, length=8):
    alpha = float(alpha)
    length = max(int(length), 1)
    hl2 = ((frame['high'] + frame['low']) / 2.0).to_numpy(dtype=float)
    price = hl2.copy()
    smooth = np.full(len(frame), np.nan, dtype=float)
    cycle = np.full(len(frame), np.nan, dtype=float)
    value1 = np.full(len(frame), np.nan, dtype=float)
    fish = np.full(len(frame), np.nan, dtype=float)
    trigger = np.full(len(frame), np.nan, dtype=float)

    k0 = (1.0 - 0.5 * alpha) ** 2
    k2 = 2.0 * (1.0 - alpha)
    k3 = (1.0 - alpha) ** 2

    for bar in range(len(frame)):
        if bar >= 3:
            smooth[bar] = (price[bar] + 2.0 * price[bar - 1] + 2.0 * price[bar - 2] + price[bar - 3]) / 6.0
        else:
            smooth[bar] = price[bar]

        if bar < 2:
            continue

        if bar < length + 3:
            cycle[bar] = (price[bar] + 2.0 * price[bar - 1] + price[bar - 2]) / 4.0
        else:
            cycle[bar] = k0 * (smooth[bar] - 2.0 * smooth[bar - 1] + smooth[bar - 2]) + k2 * cycle[bar - 1] - k3 * cycle[bar - 2]

        start = max(0, bar - length + 1)
        window = cycle[start:bar + 1]
        window = window[~np.isnan(window)]
        if window.size == 0:
            continue

        hh = np.max(window)
        ll = np.min(window)
        value1[bar] = (cycle[bar] - ll) / (hh - ll) if hh != ll else 0.0

        if bar < 3:
            continue
        vals = value1[bar - 3:bar + 1]
        if np.isnan(vals).any():
            continue
        weighted = (4.0 * vals[-1] + 3.0 * vals[-2] + 2.0 * vals[-3] + vals[-4]) / 10.0
        scaled = 1.98 * (weighted - 0.5)
        scaled = min(max(scaled, -0.999999), 0.999999)
        fish[bar] = 0.5 * math.log((1.0 + scaled) / (1.0 - scaled))
        if bar > 0 and not np.isnan(fish[bar - 1]):
            trigger[bar] = fish[bar - 1]

    out = frame.copy()
    out['fish'] = fish
    out['trigger'] = trigger
    return out.dropna(subset=['fish', 'trigger'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class FisherCyberCycleFeed(bt.feeds.PandasData):
    lines = ('fish', 'trigger')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('fish', 6), ('trigger', 7),
    )


class FisherCyberCycleStrategy(bt.Strategy):
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
        alpha=0.07,
        length=8,
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h8 = self.datas[1]
        self.fish = self.h8.fish
        self.trigger = self.h8.trigger

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
            values = [
                float(self.fish[-idx]),
                float(self.fish[-(idx + 1)]),
                float(self.trigger[-idx]),
                float(self.trigger[-(idx + 1)]),
            ]
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
        fish_now = float(self.fish[-idx])
        fish_prev = float(self.fish[-(idx + 1)])
        trig_now = float(self.trigger[-idx])
        trig_prev = float(self.trigger[-(idx + 1)])

        buy_open = buy_close = sell_open = sell_close = False
        if fish_prev <= trig_prev and fish_now > trig_now:
            if self.p.buy_pos_open:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if fish_prev >= trig_prev and fish_now < trig_now:
            if self.p.sell_pos_open:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        return buy_open, buy_close, sell_open, sell_close, fish_prev, fish_now, trig_prev, trig_now

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

        buy_open, buy_close, sell_open, sell_close, fish_prev, fish_now, trig_prev, trig_now = self._evaluate_signals()
        self.log('fisher prev={0:.4f}/{1:.4f} now={2:.4f}/{3:.4f} buy_open={4} sell_open={5}'.format(fish_prev, trig_prev, fish_now, trig_now, buy_open, sell_open))

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
