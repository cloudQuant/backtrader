from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


class RingIndex:
    def __init__(self, size):
        self.size = size
        self.count = 1
        self.map = [0] * size

    def rotate(self):
        self.count -= 1
        if self.count < 0:
            self.count = self.size - 1
        for idx in range(self.size):
            numb = idx + self.count
            if numb > self.size - 1:
                numb -= self.size
            self.map[idx] = numb


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


def compute_cycle_period(highs, lows, alpha):
    k0 = (1.0 - 0.5 * alpha) ** 2
    k1 = 2.0
    k2 = k1 * (1.0 - alpha)
    k3 = (1.0 - alpha) ** 2
    f0 = 0.0962
    f1 = 0.5769
    f2 = 0.5
    f3 = 0.08
    median = 5
    median2 = median // 2
    med2 = median % 2 == 0

    count1 = RingIndex(7)
    count2 = RingIndex(median)
    smooth = [0.0] * 7
    cycle = [0.0] * 7
    q1 = [0.0] * 7
    i1 = [0.0] * 7
    price = [0.0] * 7
    delta_phase = [0.0] * median

    inst_period = 1.0
    cperiod = 1.0
    result = []

    for bar in range(len(highs)):
        bar0 = count1.map[0]
        bar1 = count1.map[1]
        bar2 = count1.map[2]
        bar3 = count1.map[3]
        bar4 = count1.map[4]
        bar6 = count1.map[6]

        price[bar0] = (float(highs.iloc[bar]) + float(lows.iloc[bar])) / 2.0
        smooth[bar0] = (price[bar0] + 2.0 * price[bar1] + 2.0 * price[bar2] + price[bar3]) / 6.0

        if bar < 6:
            cycle[bar0] = (price[bar0] - 2.0 * price[bar1] + price[bar2]) / 4.0
        else:
            cycle[bar0] = k0 * (smooth[bar0] - k1 * smooth[bar1] + smooth[bar2]) + k2 * cycle[bar1] - k3 * cycle[bar2]

        q1[bar0] = (f0 * cycle[bar0] + f1 * cycle[bar2] - f1 * cycle[bar4] - f0 * cycle[bar6]) * (f2 + f3 * inst_period)
        i1[bar0] = cycle[bar3]

        if q1[bar0] and q1[bar1]:
            denom = 1.0 + i1[bar0] * i1[bar1] / (q1[bar0] * q1[bar1])
            delta_phase[count2.map[0]] = (i1[bar0] / q1[bar0] - i1[bar1] / q1[bar1]) / denom

        phase_idx = count2.map[0]
        delta_phase[phase_idx] = max(0.1, delta_phase[phase_idx])
        delta_phase[phase_idx] = min(1.1, delta_phase[phase_idx])

        median_values = sorted(delta_phase)
        if med2:
            median_delta = (median_values[median2] + median_values[median2 + 1]) / 2.0
        else:
            median_delta = median_values[median2]

        dc = 15.0 if not median_delta else 6.28318 / median_delta + 0.5
        inst_period = 0.67 * inst_period + 0.33 * dc
        cperiod = 0.85 * cperiod + 0.15 * inst_period
        result.append(cperiod)

        if bar < len(highs) - 1:
            count1.rotate()
            count2.rotate()

    return pd.Series(result, index=highs.index, dtype='float64')


def compute_cycle_period_signals(frame, alpha=0.07):
    value = compute_cycle_period(frame['high'], frame['low'], alpha)
    buy_signal = (value.shift(1) < value.shift(2)) & (value > value.shift(1))
    sell_signal = (value.shift(1) > value.shift(2)) & (value < value.shift(1))

    out = frame.copy()
    out['cycle_period'] = value
    out['buy_signal'] = buy_signal.astype(float)
    out['sell_signal'] = sell_signal.astype(float)
    return out.dropna(subset=['cycle_period'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class CyclePeriodFeed(bt.feeds.PandasData):
    lines = ('cycle_period', 'buy_signal', 'sell_signal')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('cycle_period', 6),
        ('buy_signal', 7),
        ('sell_signal', 8),
    )


class CyclePeriodStrategy(bt.Strategy):
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
        alpha=0.07,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h6 = self.datas[1]
        self.cycle_period = self.h6.cycle_period
        self.buy_signal = self.h6.buy_signal
        self.sell_signal = self.h6.sell_signal

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

    def _signal(self, line, idx):
        try:
            value = float(line[-idx])
        except (TypeError, ValueError, IndexError):
            return False
        return not math.isnan(value) and value > 0.5

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        try:
            float(self.cycle_period[-idx])
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

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return

        idx = max(int(self.p.signal_bar), 1)
        signal_dt = bt.num2date(self.h6.datetime[-idx])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        buy_open = self.p.buy_pos_open and self._signal(self.buy_signal, idx)
        sell_open = self.p.sell_pos_open and self._signal(self.sell_signal, idx)
        buy_close = self.p.buy_pos_close and sell_open
        sell_close = self.p.sell_pos_close and buy_open

        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1

        self.log('cycle_period={0:.6f} buy_open={1} sell_open={2}'.format(float(self.cycle_period[-idx]), buy_open, sell_open))

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
