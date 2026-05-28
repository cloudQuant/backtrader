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


class AsimmetricStochNRIndicator(bt.Indicator):
    lines = ('stoch', 'signal',)
    params = dict(
        kperiod_short=5,
        kperiod_long=12,
        dmethod='sma',
        dperiod=7,
        dphase=15,
        slowing=3,
        price_field='lowhigh',
        sens=7,
        overbought=80,
        oversold=20,
    )

    def __init__(self):
        self._kperiod0 = int(self.p.kperiod_short)
        self._kperiod1 = int(self.p.kperiod_short)
        self.addminperiod(max(self.p.kperiod_short, self.p.kperiod_long) + self.p.slowing + self.p.dperiod + 5)

    def _stoch_value(self, bar=0):
        max_value = 0.0
        min_value = 0.0
        c_value = 0.0
        for j in range(bar, bar + int(self.p.slowing)):
            if str(self.p.price_field).lower() == 'closeclose':
                window_max = max(float(self.data.close[-idx]) for idx in range(j, j + self._kperiod0))
                window_min = min(float(self.data.close[-idx]) for idx in range(j, j + self._kperiod1))
            else:
                window_max = max(float(self.data.high[-idx]) for idx in range(j, j + self._kperiod0))
                window_min = min(float(self.data.low[-idx]) for idx in range(j, j + self._kperiod1))
            max_value += window_max
            min_value += window_min
            c_value += float(self.data.close[-j])
        sens_total = float(self.p.sens) * int(self.p.slowing)
        delta = max_value - min_value
        diff = sens_total - delta
        if diff > 0:
            delta = sens_total
            min_value -= diff / 2.0
        if delta:
            return 100.0 * (c_value - min_value) / delta
        return -2.0

    def next(self):
        prev_signal = float(self.lines.signal[-1]) if len(self) > 1 else float('nan')
        self.lines.stoch[0] = self._stoch_value(0)
        values = [float(self.lines.stoch[-idx]) for idx in range(min(len(self), int(self.p.dperiod)) - 1, -1, -1)]
        self.lines.signal[0] = self._ma_window_value(values, str(self.p.dmethod), prev_signal)
        if prev_signal > float(self.p.overbought):
            self._kperiod0 = int(self.p.kperiod_short)
            self._kperiod1 = int(self.p.kperiod_long)
        if prev_signal < float(self.p.oversold):
            self._kperiod0 = int(self.p.kperiod_long)
            self._kperiod1 = int(self.p.kperiod_short)

    def _ma_window_value(self, values, method, previous=None):
        if not values:
            return float('nan')
        period = max(1, int(self.p.dperiod))
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
        if mode in {'lwma', 'wma', 'mode_lwma', 'jjma', 'mode_jjma'}:
            weights = list(range(1, len(values) + 1))
            return sum(v * w for v, w in zip(values, weights)) / sum(weights)
        return sum(values) / len(values)

    def _stoch_value_at(self, i, high_array, low_array, close_array, kperiod0, kperiod1):
        max_value = 0.0
        min_value = 0.0
        c_value = 0.0
        slowing = int(self.p.slowing)
        if i - slowing + 1 < 0:
            return float('nan')
        closeclose = str(self.p.price_field).lower() == 'closeclose'
        for j in range(slowing):
            bar = i - j
            if bar - max(kperiod0, kperiod1) + 1 < 0:
                return float('nan')
            if closeclose:
                window_max = max(float(close_array[idx]) for idx in range(bar - kperiod0 + 1, bar + 1))
                window_min = min(float(close_array[idx]) for idx in range(bar - kperiod1 + 1, bar + 1))
            else:
                window_max = max(float(high_array[idx]) for idx in range(bar - kperiod0 + 1, bar + 1))
                window_min = min(float(low_array[idx]) for idx in range(bar - kperiod1 + 1, bar + 1))
            max_value += window_max
            min_value += window_min
            c_value += float(close_array[bar])
        sens_total = float(self.p.sens) * slowing
        delta = max_value - min_value
        diff = sens_total - delta
        if diff > 0:
            delta = sens_total
            min_value -= diff / 2.0
        if delta:
            return 100.0 * (c_value - min_value) / delta
        return -2.0

    def _ma_value_at(self, values, i, previous):
        period = max(1, int(self.p.dperiod))
        mode = str(self.p.dmethod).lower()
        value = float(values[i])
        start = max(0, i - period + 1)
        window = [float(values[idx]) for idx in range(start, i + 1)]
        return self._ma_window_value(window, mode, previous)

    def once(self, start, end):
        high_array = self.data.high.array
        low_array = self.data.low.array
        close_array = self.data.close.array
        stoch_line = self.lines.stoch.array
        signal_line = self.lines.signal.array
        for line in (stoch_line, signal_line):
            while len(line) < end:
                line.append(float('nan'))

        kperiod0 = int(self.p.kperiod_short)
        kperiod1 = int(self.p.kperiod_short)
        previous_signal = None
        actual_end = min(end, len(high_array), len(low_array), len(close_array))
        for i in range(start, actual_end):
            prev_signal_for_state = previous_signal
            stoch = self._stoch_value_at(i, high_array, low_array, close_array, kperiod0, kperiod1)
            stoch_line[i] = stoch
            signal = self._ma_value_at(stoch_line, i, previous_signal)
            signal_line[i] = signal
            previous_signal = signal
            if prev_signal_for_state is not None and prev_signal_for_state > float(self.p.overbought):
                kperiod0 = int(self.p.kperiod_short)
                kperiod1 = int(self.p.kperiod_long)
            if prev_signal_for_state is not None and prev_signal_for_state < float(self.p.oversold):
                kperiod0 = int(self.p.kperiod_long)
                kperiod1 = int(self.p.kperiod_short)
        self._kperiod0 = kperiod0
        self._kperiod1 = kperiod1


class AsimmetricStochNRStrategy(bt.Strategy):
    params = dict(
        kperiod_short=5,
        kperiod_long=12,
        dmethod='sma',
        dperiod=7,
        dphase=15,
        slowing=3,
        price_field='lowhigh',
        sens=7,
        overbought=80,
        oversold=20,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = AsimmetricStochNRIndicator(
            self.data,
            kperiod_short=self.p.kperiod_short,
            kperiod_long=self.p.kperiod_long,
            dmethod=self.p.dmethod,
            dperiod=self.p.dperiod,
            dphase=self.p.dphase,
            slowing=self.p.slowing,
            price_field=self.p.price_field,
            sens=self.p.sens,
            overbought=self.p.overbought,
            oversold=self.p.oversold,
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
        stoch_prev = float(self.indicator.stoch[-shift])
        sign_prev = float(self.indicator.signal[-shift])
        stoch_cur = float(self.indicator.stoch[-shift + 1]) if shift > 1 else float(self.indicator.stoch[0])
        sign_cur = float(self.indicator.signal[-shift + 1]) if shift > 1 else float(self.indicator.signal[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if stoch_prev > sign_prev:
            if stoch_cur < sign_cur:
                buy_open = True
            sell_close = True
        if stoch_prev < sign_prev:
            if stoch_cur > sign_cur:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.kperiod_short), int(self.p.kperiod_long)) + int(self.p.slowing) + int(self.p.dperiod) + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        stoch = float(self.indicator.stoch[0])
        signal = float(self.indicator.signal[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long stoch={stoch:.4f} signal={signal:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell stoch={stoch:.4f} signal={signal:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short stoch={stoch:.4f} signal={signal:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy stoch={stoch:.4f} signal={signal:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy stoch={stoch:.4f} signal={signal:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell stoch={stoch:.4f} signal={signal:.4f}')
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
