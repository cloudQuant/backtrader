from __future__ import absolute_import, division, print_function, unicode_literals

import io
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
    if mode in {'smma', 'mode_smma'}:
        return bt.indicators.SmoothedMovingAverage
    if mode in {'lwma', 'mode_lwma'}:
        return bt.indicators.WeightedMovingAverage
    return bt.indicators.EMA


class CountSmoother:
    def __init__(self, method, period):
        self.method = str(method).lower()
        self.period = max(1, int(period))
        self.state = None
        self.values = deque(maxlen=self.period)

    def update(self, value):
        value = float(value)
        if self.method in {'sma', 'mode_sma'}:
            self.values.append(value)
            return sum(self.values) / len(self.values)
        if self.method in {'lwma', 'mode_lwma'}:
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


class JBrainTrend1SigIndicator(bt.Indicator):
    lines = ('sell_signal', 'buy_signal',)
    params = dict(
        atr_period=7,
        sto_period=9,
        ma_method='sma',
        xlength=7,
    )

    def __init__(self):
        ma_cls = resolve_ma_class(self.p.ma_method)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.highest = bt.indicators.Highest(self.data.high, period=self.p.sto_period)
        self.lowest = bt.indicators.Lowest(self.data.low, period=self.p.sto_period)
        self.jh = ma_cls(self.data.high, period=self.p.xlength)
        self.jl = ma_cls(self.data.low, period=self.p.xlength)
        self.jc = ma_cls(self.data.close, period=self.p.xlength)
        self._d = 2.3
        self._s = 1.5
        self._x1 = 53.0
        self._x2 = 47.0
        self._p_state = 0
        self._old_trend = 0
        self.addminperiod(max(self.p.atr_period, self.p.sto_period, self.p.xlength) + 3)

    def next(self):
        self.lines.sell_signal[0] = 0.0
        self.lines.buy_signal[0] = 0.0
        highest = float(self.highest[0])
        lowest = float(self.lowest[0])
        close = float(self.data.close[0])
        denom = highest - lowest
        stochastic = 50.0 if denom == 0 else 100.0 * (close - lowest) / denom
        atr_value = float(self.atr[0])
        range_value = atr_value / self._d
        range_shift = atr_value * self._s / 4.0
        val3 = abs(float(self.jc[0]) - float(self.jc[-2]))

        if stochastic < self._x2 and val3 > range_value:
            self._p_state = 1
        if stochastic > self._x1 and val3 > range_value:
            self._p_state = 2
        if val3 <= range_value:
            return

        if stochastic < self._x2 and self._p_state in (0, 1):
            if self._old_trend > 0:
                self.lines.sell_signal[0] = float(self.jh[0]) + range_shift
            if len(self.data) > 1:
                self._old_trend = -1
        if stochastic > self._x1 and self._p_state in (0, 2):
            if self._old_trend < 0:
                self.lines.buy_signal[0] = float(self.jl[0]) - range_shift
            if len(self.data) > 1:
                self._old_trend = 1


class UltraRSIIndicator(bt.Indicator):
    lines = ('bulls', 'bears',)
    params = dict(
        rsi_period=13,
        applied_price='close',
        w_method='jjma',
        start_length=3,
        nstep=5,
        nsteps_total=10,
        smooth_method='jjma',
        smooth_length=3,
    )

    def __init__(self):
        price_line = self._price_line()
        ma_cls = resolve_ma_class(self.p.w_method)
        self.rsi = bt.indicators.RSI(price_line, period=self.p.rsi_period, safediv=True)
        self._series = [
            ma_cls(self.rsi, period=max(1, int(self.p.start_length + step * self.p.nstep)))
            for step in range(int(self.p.nsteps_total) + 1)
        ]
        self._bull_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        self._bear_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        self.addminperiod(self.p.rsi_period + self.p.start_length + self.p.nstep * self.p.nsteps_total + self.p.smooth_length + 5)

    def _price_line(self):
        mode = str(self.p.applied_price).lower()
        if mode == 'open':
            return self.data.open
        if mode == 'high':
            return self.data.high
        if mode == 'low':
            return self.data.low
        if mode == 'median':
            return (self.data.high + self.data.low) / 2.0
        if mode == 'typical':
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if mode == 'weighted':
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        return self.data.close

    def next(self):
        up_count = 0
        down_count = 0
        for series in self._series:
            current = float(series[0])
            previous = float(series[-1])
            if current > previous:
                up_count += 1
            elif current < previous:
                down_count += 1
        self.lines.bulls[0] = self._bull_smoother.update(up_count)
        self.lines.bears[0] = self._bear_smoother.update(down_count)


class JBrainSig1UltraRSIStrategy(bt.Strategy):
    params = dict(
        mode='composition',
        signal_bar=1,
        atr_period=7,
        sto_period=9,
        ma_method='sma',
        xlength=7,
        xphase=100,
        rsi_period=13,
        applied_price='close',
        w_method='jjma',
        start_length=3,
        wphase=100,
        nstep=5,
        nsteps_total=10,
        smooth_method='jjma',
        smooth_length=3,
        smooth_phase=100,
        lot=0.1,
        point=0.01,
        price_digits=2,
        fallback_price_momentum=True,
        max_signal_lookback=500,
    )

    def __init__(self):
        self.jbrain = JBrainTrend1SigIndicator(
            self.data,
            atr_period=self.p.atr_period,
            sto_period=self.p.sto_period,
            ma_method=self.p.ma_method,
            xlength=self.p.xlength,
        )
        self.ultra_rsi = UltraRSIIndicator(
            self.data,
            rsi_period=self.p.rsi_period,
            applied_price=self.p.applied_price,
            w_method=self.p.w_method,
            start_length=self.p.start_length,
            nstep=self.p.nstep,
            nsteps_total=self.p.nsteps_total,
            smooth_method=self.p.smooth_method,
            smooth_length=self.p.smooth_length,
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

    def _latest_jbrain_state(self):
        signal_bar = max(1, int(self.p.signal_bar))
        max_lookback = min(len(self.data) - 1, int(self.p.max_signal_lookback))
        buy_open_1 = False
        sell_open_1 = False
        buy_close_1 = False
        sell_close_1 = False
        for shift in range(signal_bar, max_lookback + 1):
            sell_value = float(self.jbrain.sell_signal[-shift])
            buy_value = float(self.jbrain.buy_signal[-shift])
            if sell_value != 0.0:
                buy_close_1 = True
                if shift == signal_bar:
                    sell_open_1 = True
                break
            if buy_value != 0.0:
                sell_close_1 = True
                if shift == signal_bar:
                    buy_open_1 = True
                break
        return buy_open_1, sell_open_1, buy_close_1, sell_close_1

    def _ultra_rsi_state(self):
        shift = max(1, int(self.p.signal_bar))
        current_bulls = float(self.ultra_rsi.bulls[-shift])
        previous_bulls = float(self.ultra_rsi.bulls[-shift - 1])
        current_bears = float(self.ultra_rsi.bears[-shift])
        previous_bears = float(self.ultra_rsi.bears[-shift - 1])
        buy_open_2 = previous_bulls <= previous_bears and current_bulls > current_bears
        sell_close_2 = current_bulls > current_bears
        sell_open_2 = previous_bears <= previous_bulls and current_bears > current_bulls
        buy_close_2 = current_bears > current_bulls
        return buy_open_2, sell_open_2, buy_close_2, sell_close_2, current_bulls, current_bears

    def next(self):
        self.bar_num += 1
        min_bars = max(
            int(self.p.atr_period),
            int(self.p.sto_period),
            int(self.p.xlength),
            int(self.p.rsi_period + self.p.start_length + self.p.nstep * self.p.nsteps_total + self.p.smooth_length),
        ) + int(self.p.signal_bar) + 5
        if len(self.data) < min_bars:
            return

        buy_open_1, sell_open_1, buy_close_1, sell_close_1 = self._latest_jbrain_state()
        buy_open_2, sell_open_2, buy_close_2, sell_close_2, bulls_value, bears_value = self._ultra_rsi_state()

        mode = str(self.p.mode).lower()
        buy_open = False
        sell_open = False
        if mode == 'jbrainsig1filter':
            buy_open = buy_open_2 and sell_close_1
            sell_open = sell_open_2 and buy_close_1
        elif mode == 'ultrarsifilter':
            buy_open = buy_open_1 and sell_close_2
            sell_open = sell_open_1 and buy_close_2
        elif mode == 'ultrarsi':
            buy_open = sell_close_2
            sell_open = buy_close_2
        else:
            buy_open = (buy_open_1 and sell_close_2) or (buy_open_2 and sell_close_1)
            sell_open = (sell_open_1 and buy_close_2) or (sell_open_2 and buy_close_1)
        if mode == 'ultrarsi' and bool(self.p.fallback_price_momentum) and not buy_open and not sell_open:
            if float(self.data.close[0]) > float(self.data.close[-1]):
                buy_open = True
            elif float(self.data.close[0]) < float(self.data.close[-1]):
                sell_open = True

        if mode == 'ultrarsi':
            sell_close = sell_close_2
            buy_close = buy_close_2
        else:
            sell_close = sell_close_1 and sell_close_2
            buy_close = buy_close_1 and buy_close_2

        if self.position:
            if self.position.size > 0:
                if buy_close:
                    self.log(f'close long bulls={bulls_value:.2f} bears={bears_value:.2f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell bulls={bulls_value:.2f} bears={bears_value:.2f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close:
                    self.log(f'close short bulls={bulls_value:.2f} bears={bears_value:.2f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy bulls={bulls_value:.2f} bears={bears_value:.2f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy bulls={bulls_value:.2f} bears={bears_value:.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell bulls={bulls_value:.2f} bears={bears_value:.2f}')
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
