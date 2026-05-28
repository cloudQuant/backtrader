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
    if mode in {'ema', 'mode_ema'}:
        return bt.indicators.EMA
    if mode in {'smma', 'mode_smma'}:
        return bt.indicators.SmoothedMovingAverage
    return bt.indicators.WeightedMovingAverage


class RollingWeightedAverage:
    def __init__(self, period):
        self.period = max(1, int(period))
        self.values = deque(maxlen=self.period)

    def update(self, value):
        self.values.append(float(value))
        weights = list(range(len(self.values), 0, -1))
        return sum(v * w for v, w in zip(self.values, weights)) / sum(weights)


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


class TRVIIndicator(bt.Indicator):
    lines = ('trvi', 'signal',)
    params = dict(period=26, volume_type='tick')

    def __init__(self):
        self._num_avg = RollingWeightedAverage(self.p.period)
        self._den_avg = RollingWeightedAverage(self.p.period)
        self._signal_window = deque(maxlen=4)
        self.addminperiod(self.p.period + 8)

    def _volume(self):
        if str(self.p.volume_type).lower() == 'real':
            return float(self.data.openinterest[0]) if len(self.data.openinterest) else float(self.data.volume[0])
        return float(self.data.volume[0])

    def _count_val(self, a_now, b_now, a_prev1, b_prev1, a_prev2, b_prev2, a_prev3, b_prev3, vol_now, vol_prev1, vol_prev2, vol_prev3):
        return (
            vol_now * (a_now - b_now)
            + 8.0 * vol_prev1 * (a_prev1 - b_prev1)
            + 8.0 * vol_prev2 * (a_prev2 - b_prev2)
            + vol_prev3 * (a_prev3 - b_prev3)
        )

    def next(self):
        volume_now = self._volume()
        volume_prev1 = float(self.data.volume[-1])
        volume_prev2 = float(self.data.volume[-2])
        volume_prev3 = float(self.data.volume[-3])
        num_value = self._count_val(
            float(self.data.close[0]), float(self.data.open[0]),
            float(self.data.close[-1]), float(self.data.open[-1]),
            float(self.data.close[-2]), float(self.data.open[-2]),
            float(self.data.close[-3]), float(self.data.open[-3]),
            volume_now, volume_prev1, volume_prev2, volume_prev3,
        )
        den_value = self._count_val(
            float(self.data.high[0]), float(self.data.low[0]),
            float(self.data.high[-1]), float(self.data.low[-1]),
            float(self.data.high[-2]), float(self.data.low[-2]),
            float(self.data.high[-3]), float(self.data.low[-3]),
            volume_now, volume_prev1, volume_prev2, volume_prev3,
        )
        smooth_num = self._num_avg.update(num_value)
        smooth_den = self._den_avg.update(den_value)
        trvi_value = smooth_num / smooth_den if smooth_den else 0.0
        self.lines.trvi[0] = trvi_value
        self._signal_window.appendleft(trvi_value)
        if len(self._signal_window) == 4:
            self.lines.signal[0] = (
                4.0 * self._signal_window[0]
                + 3.0 * self._signal_window[1]
                + 2.0 * self._signal_window[2]
                + self._signal_window[3]
            ) / 10.0
        else:
            self.lines.signal[0] = trvi_value


class ColorRMACDIndicator(bt.Indicator):
    lines = ('rmacd', 'signal',)
    params = dict(
        fast_rvi=12,
        slow_trvi=26,
        volume_type='tick',
        signal_method='sma',
        signal_xma=9,
    )

    def __init__(self):
        ma_cls = resolve_ma_class(self.p.signal_method)
        self.rvi = bt.indicators.RSI(self.data.close, period=self.p.fast_rvi, safediv=True)
        self.trvi = TRVIIndicator(self.data, period=self.p.slow_trvi, volume_type=self.p.volume_type)
        self.lines.rmacd = self.rvi - self.trvi.signal
        self.lines.signal = ma_cls(self.lines.rmacd, period=self.p.signal_xma)
        self.addminperiod(max(self.p.fast_rvi, self.p.slow_trvi + 8, self.p.signal_xma) + 5)


class RMACDStrategy(bt.Strategy):
    params = dict(
        mode='macddisposition',
        fast_rvi=12,
        slow_trvi=26,
        volume_type='tick',
        signal_method='sma',
        signal_xma=9,
        signal_phase=100,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = ColorRMACDIndicator(
            self.data,
            fast_rvi=self.p.fast_rvi,
            slow_trvi=self.p.slow_trvi,
            volume_type=self.p.volume_type,
            signal_method=self.p.signal_method,
            signal_xma=self.p.signal_xma,
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

    def _mode_signals(self):
        shift = max(1, int(self.p.signal_bar))
        mode = str(self.p.mode).lower()
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False

        if mode == 'breakdown':
            current = float(self.indicator.rmacd[-shift])
            previous = float(self.indicator.rmacd[-shift - 1])
            if previous > 0:
                if current <= 0:
                    buy_open = True
                sell_close = True
            if previous < 0:
                if current >= 0:
                    sell_open = True
                buy_close = True
            return buy_open, sell_open, buy_close, sell_close

        if mode == 'macdtwist':
            current = float(self.indicator.rmacd[-shift])
            previous = float(self.indicator.rmacd[-shift - 1])
            prev2 = float(self.indicator.rmacd[-shift - 2])
            if previous < prev2:
                if current > previous:
                    buy_open = True
                sell_close = True
            if previous > prev2:
                if current < previous:
                    sell_open = True
                buy_close = True
            return buy_open, sell_open, buy_close, sell_close

        if mode == 'signaltwist':
            current = float(self.indicator.signal[-shift])
            previous = float(self.indicator.signal[-shift - 1])
            prev2 = float(self.indicator.signal[-shift - 2])
            if previous < prev2:
                if current > previous:
                    buy_open = True
                sell_close = True
            if previous > prev2:
                if current < previous:
                    sell_open = True
                buy_close = True
            return buy_open, sell_open, buy_close, sell_close

        macd_current = float(self.indicator.rmacd[-shift])
        macd_previous = float(self.indicator.rmacd[-shift - 1])
        signal_current = float(self.indicator.signal[-shift])
        signal_previous = float(self.indicator.signal[-shift - 1])
        if macd_previous > signal_previous:
            if macd_current <= signal_current:
                buy_open = True
            sell_close = True
        if macd_previous < signal_previous:
            if macd_current >= signal_current:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        min_bars = max(int(self.p.fast_rvi), int(self.p.slow_trvi) + 8, int(self.p.signal_xma)) + int(self.p.signal_bar) + 5
        if len(self.data) < min_bars:
            return

        buy_open, sell_open, buy_close, sell_close = self._mode_signals()
        current_macd = float(self.indicator.rmacd[0])
        current_signal = float(self.indicator.signal[0])

        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long macd={current_macd:.4f} signal={current_signal:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell macd={current_macd:.4f} signal={current_signal:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short macd={current_macd:.4f} signal={current_signal:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy macd={current_macd:.4f} signal={current_signal:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy macd={current_macd:.4f} signal={current_signal:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell macd={current_macd:.4f} signal={current_signal:.4f}')
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
