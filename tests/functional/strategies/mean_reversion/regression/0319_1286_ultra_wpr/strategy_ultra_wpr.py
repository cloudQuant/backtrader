from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from collections import deque
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3] / 'backtrader'
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import backtrader as bt
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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


def resolve_ma_class(name):
    mode = str(name).lower()
    if mode in {'sma', 'mode_sma'}:
        return bt.indicators.SMA
    if mode in {'ema', 'mode_ema'}:
        return bt.indicators.EMA
    if mode in {'smma', 'mode_smma'}:
        return bt.indicators.SmoothedMovingAverage
    return bt.indicators.WeightedMovingAverage


class CountSmoother:
    def __init__(self, method, period):
        self.method = str(method).lower()
        self.period = max(1, int(period))
        self.values = deque(maxlen=self.period)
        self.state = None

    def update(self, value):
        value = float(value)
        if self.method in {'sma', 'mode_sma'}:
            self.values.append(value)
            return sum(self.values) / len(self.values)
        if self.method in {'lwma', 'mode_lwma', 'jjma', 'mode_jjma'}:
            self.values.append(value)
            weights = list(range(1, len(self.values) + 1))
            return sum(v * w for v, w in zip(self.values, weights)) / sum(weights)
        if self.method in {'smma', 'mode_smma'}:
            if self.state is None:
                self.state = value
            else:
                self.state = ((self.period - 1) * self.state + value) / self.period
            return self.state
        alpha = 2.0 / (self.period + 1.0)
        if self.state is None:
            self.state = value
        else:
            self.state = self.state + alpha * (value - self.state)
        return self.state


class UltraWPRIndicator(bt.Indicator):
    lines = ('bulls', 'bears',)
    params = dict(
        wpr_period=13,
        w_method='jjma',
        start_length=3,
        w_phase=100,
        xstep=5,
        xsteps_total=10,
        smooth_method='jjma',
        smooth_length=3,
        smooth_phase=100,
    )

    def __init__(self):
        self._periods = [int(self.p.start_length + self.p.xstep * i) for i in range(int(self.p.xsteps_total) + 1)]
        self._wpr_indicators = [bt.indicators.WilliamsR(self.data, period=self.p.wpr_period) for _ in self._periods]
        self._smoothers = [CountSmoother(self.p.w_method, period) for period in self._periods]
        self._prev_values = [None for _ in self._periods]
        self._bull_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        self._bear_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        self.addminperiod(self.p.wpr_period + max(self._periods) + self.p.smooth_length + 5)

    def next(self):
        upsch = 0.0
        dnsch = 0.0
        current_values = []
        base_wpr = float(self._wpr_indicators[0][0])
        if math.isnan(base_wpr):
            self.lines.bulls[0] = float('nan')
            self.lines.bears[0] = float('nan')
            return
        for index, smoother in enumerate(self._smoothers):
            value = smoother.update(base_wpr)
            current_values.append(value)
            prev = self._prev_values[index]
            if prev is None:
                continue
            if value > prev:
                upsch += 1.0
            else:
                dnsch += 1.0
        self.lines.bulls[0] = self._bull_smoother.update(upsch)
        self.lines.bears[0] = self._bear_smoother.update(dnsch)
        self._prev_values = current_values

    def once(self, start, end):
        base_wpr_array = self._wpr_indicators[0].lines[0].array
        bulls_line = self.lines.bulls.array
        bears_line = self.lines.bears.array
        for line in (bulls_line, bears_line):
            while len(line) < end:
                line.append(float('nan'))

        smoothers = [CountSmoother(self.p.w_method, period) for period in self._periods]
        prev_values = [None for _ in self._periods]
        bull_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        bear_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        actual_end = min(end, len(base_wpr_array))
        for i in range(start, actual_end):
            upsch = 0.0
            dnsch = 0.0
            current_values = []
            base_wpr = float(base_wpr_array[i])
            if math.isnan(base_wpr):
                bulls_line[i] = float('nan')
                bears_line[i] = float('nan')
                continue
            for index, smoother in enumerate(smoothers):
                value = smoother.update(base_wpr)
                current_values.append(value)
                prev = prev_values[index]
                if prev is None:
                    continue
                if value > prev:
                    upsch += 1.0
                else:
                    dnsch += 1.0
            bulls_line[i] = bull_smoother.update(upsch)
            bears_line[i] = bear_smoother.update(dnsch)
            prev_values = current_values

        self._smoothers = smoothers
        self._prev_values = prev_values
        self._bull_smoother = bull_smoother
        self._bear_smoother = bear_smoother


class UltraWPRStrategy(bt.Strategy):
    params = dict(
        wpr_period=13,
        w_method='jjma',
        start_length=3,
        w_phase=100,
        xstep=5,
        xsteps_total=10,
        smooth_method='jjma',
        smooth_length=3,
        smooth_phase=100,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = UltraWPRIndicator(
            self.data,
            wpr_period=self.p.wpr_period,
            w_method=self.p.w_method,
            start_length=self.p.start_length,
            w_phase=self.p.w_phase,
            xstep=self.p.xstep,
            xsteps_total=self.p.xsteps_total,
            smooth_method=self.p.smooth_method,
            smooth_length=self.p.smooth_length,
            smooth_phase=self.p.smooth_phase,
        )
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        up_prev = float(self.indicator.bulls[-shift - 1])
        dn_prev = float(self.indicator.bears[-shift - 1])
        up_cur = float(self.indicator.bulls[-shift])
        dn_cur = float(self.indicator.bears[-shift])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if up_prev > dn_prev:
            if up_cur <= dn_cur:
                buy_open = True
            sell_close = True
        if dn_prev > up_prev:
            if dn_cur <= up_cur:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.wpr_period + self.p.start_length + self.p.xstep * self.p.xsteps_total + self.p.smooth_length + self.p.signal_bar + 5)
        if len(self.data) < warmup:
            return
        if math.isnan(float(self.indicator.bulls[0])) or math.isnan(float(self.indicator.bears[0])):
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        bulls = float(self.indicator.bulls[0])
        bears = float(self.indicator.bears[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long bulls={bulls:.4f} bears={bears:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell bulls={bulls:.4f} bears={bears:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short bulls={bulls:.4f} bears={bears:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy bulls={bulls:.4f} bears={bears:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy bulls={bulls:.4f} bears={bears:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell bulls={bulls:.4f} bears={bears:.4f}')
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
