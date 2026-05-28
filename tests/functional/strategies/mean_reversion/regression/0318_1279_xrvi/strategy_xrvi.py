from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
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


class XRVIIndicator(bt.Indicator):
    lines = ('xrvi', 'signal',)
    params = dict(
        rvi_method='jurx',
        rvi_period=10,
        rvi_phase=15,
        sign_method='jurx',
        sign_period=5,
        sign_phase=15,
    )

    def __init__(self):
        self.addminperiod(self.p.rvi_period + self.p.sign_period + 3)

    def _raw_rvi_at(self, i, open_array, high_array, low_array, close_array):
        denom = float(high_array[i]) - float(low_array[i])
        return (float(close_array[i]) - float(open_array[i])) / denom if denom else 0.0

    def _window_ma(self, values, method, period, previous=None):
        if not values:
            return float('nan')
        mode = str(method).lower()
        value = float(values[-1])
        if mode in {'ema', 'mode_ema'}:
            if previous is None or previous != previous:
                return value
            alpha = 2.0 / (period + 1.0)
            return previous + alpha * (value - previous)
        if mode in {'smma', 'mode_smma'}:
            if previous is None or previous != previous:
                return value
            return ((period - 1.0) * previous + value) / period
        if mode in {'sma', 'mode_sma'}:
            return sum(values) / len(values)
        weights = list(range(1, len(values) + 1))
        return sum(v * w for v, w in zip(values, weights)) / sum(weights)

    def _raw_rvi_ago(self, ago):
        denom = float(self.data.high[-ago]) - float(self.data.low[-ago])
        return (float(self.data.close[-ago]) - float(self.data.open[-ago])) / denom if denom else 0.0

    def next(self):
        rvi_period = max(1, int(self.p.rvi_period))
        sign_period = max(1, int(self.p.sign_period))
        raw_window = [self._raw_rvi_ago(ago) for ago in range(min(len(self), rvi_period) - 1, -1, -1)]
        prev_xrvi = float(self.lines.xrvi[-1]) if len(self) > 1 else None
        xrvi = self._window_ma(raw_window, self.p.rvi_method, rvi_period, prev_xrvi)
        self.lines.xrvi[0] = xrvi
        signal_values = []
        for ago in range(min(len(self), sign_period) - 1, 0, -1):
            value = float(self.lines.xrvi[-ago])
            if value == value:
                signal_values.append(value)
        signal_values.append(xrvi)
        prev_signal = float(self.lines.signal[-1]) if len(self) > 1 else None
        self.lines.signal[0] = self._window_ma(signal_values, self.p.sign_method, sign_period, prev_signal)

    def once(self, start, end):
        open_array = self.data.open.array
        high_array = self.data.high.array
        low_array = self.data.low.array
        close_array = self.data.close.array
        xrvi_line = self.lines.xrvi.array
        signal_line = self.lines.signal.array
        for line in (xrvi_line, signal_line):
            while len(line) < end:
                line.append(float('nan'))

        rvi_period = max(1, int(self.p.rvi_period))
        sign_period = max(1, int(self.p.sign_period))
        prev_xrvi = None
        prev_signal = None
        actual_end = min(end, len(open_array), len(high_array), len(low_array), len(close_array))
        raw_values = [self._raw_rvi_at(i, open_array, high_array, low_array, close_array) for i in range(actual_end)]
        xrvi_values = []
        for i in range(actual_end):
            raw_start = max(0, i - rvi_period + 1)
            xrvi = self._window_ma(raw_values[raw_start:i + 1], self.p.rvi_method, rvi_period, prev_xrvi)
            xrvi_values.append(xrvi)
            if i >= start:
                xrvi_line[i] = xrvi
            prev_xrvi = xrvi
            signal_start = max(0, i - sign_period + 1)
            signal_values = xrvi_values[signal_start:i + 1]
            signal = self._window_ma(signal_values, self.p.sign_method, sign_period, prev_signal)
            if i >= start:
                signal_line[i] = signal
            prev_signal = signal


class XRVIStrategy(bt.Strategy):
    params = dict(
        rvi_method='jurx',
        rvi_period=10,
        rvi_phase=15,
        sign_method='jurx',
        sign_period=5,
        sign_phase=15,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = XRVIIndicator(
            self.data,
            rvi_method=self.p.rvi_method,
            rvi_period=self.p.rvi_period,
            rvi_phase=self.p.rvi_phase,
            sign_method=self.p.sign_method,
            sign_period=self.p.sign_period,
            sign_phase=self.p.sign_phase,
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
        value_prev = float(self.indicator.xrvi[-shift])
        sig_prev = float(self.indicator.signal[-shift])
        value_cur = float(self.indicator.xrvi[-shift + 1]) if shift > 1 else float(self.indicator.xrvi[0])
        sig_cur = float(self.indicator.signal[-shift + 1]) if shift > 1 else float(self.indicator.signal[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if value_prev > sig_prev:
            if value_cur <= sig_cur:
                buy_open = True
            sell_close = True
        if value_prev < sig_prev:
            if value_cur >= sig_cur:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.rvi_period) + int(self.p.sign_period) + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.xrvi[0])
        signal = float(self.indicator.signal[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long xrvi={value:.4f} signal={signal:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell xrvi={value:.4f} signal={signal:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short xrvi={value:.4f} signal={signal:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy xrvi={value:.4f} signal={signal:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy xrvi={value:.4f} signal={signal:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell xrvi={value:.4f} signal={signal:.4f}')
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
