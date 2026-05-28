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
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    base_columns = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']
    if 'spread' in df.columns:
        base_columns.append('spread')
    df = df[base_columns]
    df = df.set_index('datetime').sort_index()
    if 'spread' not in df.columns:
        df['spread'] = 0.0
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class SinewaveFeed(bt.feeds.PandasData):
    lines = ('main_line', 'signal_line')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('main_line', 6),
        ('signal_line', 7),
    )


def build_resampled_frame(df, indicator_minutes):
    rule = f'{int(indicator_minutes)}min'
    signal_df = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    signal_df = signal_df.dropna(subset=['open', 'high', 'low', 'close']).copy()
    signal_df['openinterest'] = signal_df['openinterest'].fillna(0.0)
    return signal_df


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


def compute_sinewave2(df, alpha):
    cycle_period = compute_cycle_period(df['high'], df['low'], alpha)
    max_period = 50
    count = RingIndex(max_period)
    smooth = [0.0] * max_period
    price = [0.0] * max_period
    cycle = [0.0] * max_period
    k0 = (1.0 - 0.5 * alpha) ** 2
    k1 = 2.0
    k2 = k1 * (1.0 - alpha)
    k3 = (1.0 - alpha) ** 2
    rad2deg = 45.0 / math.atan(1.0)
    deg2rad = 1.0 / rad2deg
    sine_line = []
    lead_sine_line = []

    for bar in range(len(df)):
        bar0 = count.map[0]
        bar1 = count.map[1]
        bar2 = count.map[2]
        bar3 = count.map[3]
        price[bar0] = (float(df.iloc[bar]['high']) + float(df.iloc[bar]['low'])) / 2.0
        smooth[bar0] = (price[bar0] + 2.0 * price[bar1] + 2.0 * price[bar2] + price[bar3]) / 6.0

        if bar > 7:
            cycle[bar0] = k0 * (smooth[bar0] - k1 * smooth[bar1] + smooth[bar2]) + k2 * cycle[bar1] - k3 * cycle[bar2]
        else:
            cycle[bar0] = (price[bar0] - 2.0 * price[bar1] + price[bar2]) / 4.0

        dc_period = int(math.floor(float(cycle_period.iloc[bar])))
        dc_period = min(dc_period, bar, max_period)
        real_part = 0.0
        imag_part = 0.0

        if dc_period > 0:
            for iii in range(dc_period):
                arg = deg2rad * 360.0 * iii / dc_period
                cycle_value = cycle[count.map[iii]]
                real_part += math.sin(arg) * cycle_value
                imag_part += math.cos(arg) * cycle_value

        if abs(imag_part) > 0.001:
            dc_phase = rad2deg * math.atan(real_part / imag_part)
        else:
            dc_phase = 90.0 if real_part >= 0.0 else -90.0

        dc_phase += 90.0
        if imag_part < 0.0:
            dc_phase += 180.0
        if dc_phase > 315.0:
            dc_phase -= 360.0

        sine_value = math.sin(dc_phase * deg2rad)
        lead_value = math.sin((dc_phase + 45.0) * deg2rad)
        prev_lead = lead_sine_line[-1] if lead_sine_line else 0.0
        if dc_phase == 180.0 and prev_lead > 0.0:
            lead_value = math.sin(45.0 * deg2rad)
        if dc_phase == 0.0 and prev_lead < 0.0:
            lead_value = math.sin(225.0 * deg2rad)

        sine_line.append(sine_value)
        lead_sine_line.append(lead_value)

        if bar < len(df) - 1:
            count.rotate()

    return (
        pd.Series(sine_line, index=df.index, dtype='float64'),
        pd.Series(lead_sine_line, index=df.index, dtype='float64'),
    )


def build_sinewave_frame(df, indicator_minutes, alpha):
    signal_df = build_resampled_frame(df, indicator_minutes)
    main_line, signal_line = compute_sinewave2(signal_df, alpha)
    signal_df = signal_df.copy()
    signal_df['main_line'] = main_line
    signal_df['signal_line'] = signal_line
    signal_df = signal_df.dropna(subset=['main_line', 'signal_line'])
    return signal_df


class ExpSinewave2X2Strategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stop_loss_points=1000,
        take_profit_points=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close_trend=True,
        sell_pos_close_trend=True,
        buy_pos_close_signal=False,
        sell_pos_close_signal=False,
        alpha_slow=0.07,
        alpha_fast=0.07,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.slow_feed = self.datas[1]
        self.fast_feed = self.datas[2]
        self.entry_order = None
        self.close_order = None
        self.pending_side = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None
        self.buy_count = 0
        self.sell_count = 0
        self.last_fast_dt = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _submit_close_side(self, side, reason):
        if not self.position:
            return
        if side == 'long' and self.position.size <= 0:
            return
        if side == 'short' and self.position.size >= 0:
            return
        self._submit_close(reason)

    def _submit_entry(self, side, reason):
        if self.entry_order is not None or self.close_order is not None:
            self.pending_side = side
            return
        if self.position.size > 0 and side == 'long':
            return
        if self.position.size < 0 and side == 'short':
            return
        if self.position:
            self.pending_side = side
            self._submit_close(f'reverse to {side}: {reason}')
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.pending_side = None
        if side == 'long':
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN LONG size={size} reason={reason}')
        else:
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SHORT size={size} reason={reason}')

    def _check_protective_exit(self):
        if not self.position or self.close_order is not None:
            return
        bar_high = float(self.data0_feed.high[0])
        bar_low = float(self.data0_feed.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and bar_low <= self.stop_price:
                self._submit_close('stop loss hit')
                return
            if self.limit_price is not None and bar_high >= self.limit_price:
                self._submit_close('take profit hit')
                return
        else:
            if self.stop_price is not None and bar_high >= self.stop_price:
                self._submit_close('stop loss hit')
                return
            if self.limit_price is not None and bar_low <= self.limit_price:
                self._submit_close('take profit hit')
                return

    def next(self):
        if len(self.data0_feed) < 10 or len(self.slow_feed) < 2 or len(self.fast_feed) < 2:
            return
        self._check_protective_exit()
        fast_dt = bt.num2date(self.fast_feed.datetime[0])
        if self.last_fast_dt == fast_dt:
            return
        self.last_fast_dt = fast_dt
        if self.entry_order is not None or self.close_order is not None:
            return

        slow_signal = float(self.slow_feed.signal_line[0])
        slow_main = float(self.slow_feed.main_line[0])
        fast_signal_now = float(self.fast_feed.signal_line[0])
        fast_main_now = float(self.fast_feed.main_line[0])
        fast_signal_prev = float(self.fast_feed.signal_line[-1])
        fast_main_prev = float(self.fast_feed.main_line[-1])

        if self.p.buy_pos_close_signal and fast_signal_now < fast_main_now:
            self._submit_close_side('long', 'fast sine below fast main')
        if self.p.sell_pos_close_signal and fast_signal_now > fast_main_now:
            self._submit_close_side('short', 'fast sine above fast main')
        if self.entry_order is not None or self.close_order is not None:
            return

        trend = 0
        if slow_signal < slow_main:
            trend = -1
        elif slow_signal > slow_main:
            trend = 1

        cross_up = fast_signal_now >= fast_main_now and fast_signal_prev < fast_main_prev
        cross_down = fast_signal_now <= fast_main_now and fast_signal_prev > fast_main_prev

        if trend < 0:
            if self.p.buy_pos_close_trend:
                self._submit_close_side('long', 'slow trend turned bearish')
            if self.entry_order is None and self.close_order is None and self.p.sell_pos_open and cross_up:
                self._submit_entry('short', 'slow trend bearish and fast signal crossed above fast main')
        elif trend > 0:
            if self.p.sell_pos_close_trend:
                self._submit_close_side('short', 'slow trend turned bullish')
            if self.entry_order is None and self.close_order is None and self.p.buy_pos_open and cross_down:
                self._submit_entry('long', 'slow trend bullish and fast signal crossed below fast main')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_price = order.executed.price
                stop_distance = float(self.p.stop_loss_points) * float(self.p.point_size)
                limit_distance = float(self.p.take_profit_points) * float(self.p.point_size)
                if self.active_side == 'long':
                    self.stop_price = self.entry_price - stop_distance if self.p.stop_loss_points > 0 else None
                    self.limit_price = self.entry_price + limit_distance if self.p.take_profit_points > 0 else None
                else:
                    self.stop_price = self.entry_price + stop_distance if self.p.stop_loss_points > 0 else None
                    self.limit_price = self.entry_price - limit_distance if self.p.take_profit_points > 0 else None
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self.stop_price = None
                self.limit_price = None
                if self.pending_side is not None:
                    next_side = self.pending_side
                    self.pending_side = None
                    self._submit_entry(next_side, 'post-close reversal')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.entry_price = None
            self.stop_price = None
            self.limit_price = None
