from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
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
    if mode in {'mode_sma', 'sma'}:
        return bt.indicators.SimpleMovingAverage
    if mode in {'mode_ema', 'ema', 'mode_jjma', 'jjma', 'mode_jurx', 'jurx', 'mode_parma', 'parma', 'mode_t3', 't3', 'mode_vidya', 'vidya', 'mode_ama', 'ama'}:
        return bt.indicators.ExponentialMovingAverage
    if mode in {'mode_smma', 'smma'}:
        return bt.indicators.SmoothedMovingAverage
    return bt.indicators.WeightedMovingAverage


def resolve_price_line(data, mode):
    price_mode = str(mode).lower()
    if price_mode in {'price_open', 'open'}:
        return data.open
    if price_mode in {'price_high', 'high'}:
        return data.high
    if price_mode in {'price_low', 'low'}:
        return data.low
    if price_mode in {'price_median', 'median'}:
        return (data.high + data.low) / 2.0
    if price_mode in {'price_typical', 'typical'}:
        return (data.high + data.low + data.close) / 3.0
    if price_mode in {'price_weighted', 'weighted'}:
        return (2.0 * data.close + data.high + data.low) / 4.0
    if price_mode in {'price_simpl', 'simpl'}:
        return (data.open + data.close) / 2.0
    if price_mode in {'price_quarter', 'quarter'}:
        return (data.open + data.close + data.high + data.low) / 4.0
    return data.close


class EFDistanceIndicator(bt.Indicator):
    lines = ('value',)
    params = dict(length=10, power=2.0, ipc='price_close', price_shift=0.0)

    def __init__(self):
        self.addminperiod(int(self.p.length) * 2 + 2)

    def next(self):
        length = int(self.p.length)
        current_price = float(resolve_price_line(self.data, self.p.ipc)[0])
        weights = []
        prices = []
        for i in range(length):
            base_price = float(resolve_price_line(self.data, self.p.ipc)[-i])
            energy = 0.0
            for j in range(length):
                ref_price = float(resolve_price_line(self.data, self.p.ipc)[-(i + j)])
                energy += abs((base_price - ref_price) ** float(self.p.power))
            weights.append(energy)
            prices.append(base_price)
        norm = sum(weights)
        value = sum(w * p for w, p in zip(weights, prices)) / norm if norm else 0.0
        self.lines.value[0] = value + float(self.p.price_shift)


class FlatTrendIndicator(bt.Indicator):
    lines = ('state',)
    params = dict(
        stdev_period=20,
        stdev_method='lwma',
        stdev_length=5,
        stdev_phase=15,
        atr_period=20,
        atr_method='lwma',
        atr_length=5,
        atr_phase=15,
    )

    def __init__(self):
        self._atr = bt.indicators.AverageTrueRange(self.data, period=max(1, int(self.p.atr_period)))
        self._std = bt.indicators.StandardDeviation(self.data.close, period=max(1, int(self.p.stdev_period)))
        atr_ma = resolve_ma_class(self.p.atr_method)
        std_ma = resolve_ma_class(self.p.stdev_method)
        self._xatr = atr_ma(self._atr, period=max(1, int(self.p.atr_length)))
        self._xstd = std_ma(self._std, period=max(1, int(self.p.stdev_length)))
        self.addminperiod(max(int(self.p.atr_period) + int(self.p.atr_length), int(self.p.stdev_period) + int(self.p.stdev_length)) + 3)

    def next(self):
        prev_xatr = float(self._xatr[-1])
        prev_xstd = float(self._xstd[-1])
        xatr = float(self._xatr[0])
        xstd = float(self._xstd[0])
        res = 0
        if prev_xatr > xatr and prev_xstd > xstd:
            res = 1
        if prev_xatr < xatr and prev_xstd < xstd:
            res = 2
        self.lines.state[0] = res + 1


class EFDistanceStrategy(bt.Strategy):
    params = dict(
        xlength=10,
        power=2.0,
        ipc='price_close',
        signal_bar=1,
        stdev_period=20,
        stdev_method='lwma',
        stdev_length=5,
        stdev_phase=15,
        atr_period=20,
        atr_method='lwma',
        atr_length=5,
        atr_phase=15,
        volatil='v3',
        lot=0.1,
    )

    def __init__(self):
        self.indicator = EFDistanceIndicator(self.data, length=self.p.xlength, power=self.p.power, ipc=self.p.ipc)
        self.flat_trend = FlatTrendIndicator(
            self.data,
            stdev_period=self.p.stdev_period,
            stdev_method=self.p.stdev_method,
            stdev_length=self.p.stdev_length,
            stdev_phase=self.p.stdev_phase,
            atr_period=self.p.atr_period,
            atr_method=self.p.atr_method,
            atr_length=self.p.atr_length,
            atr_phase=self.p.atr_phase,
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

    def _volatility_threshold(self):
        mode = str(self.p.volatil).lower()
        if mode == 'v1':
            return 1.0
        if mode == 'v2':
            return 2.0
        return 2.0

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        value0 = float(self.indicator.value[-shift + 1]) if shift > 1 else float(self.indicator.value[0])
        value1 = float(self.indicator.value[-shift])
        value2 = float(self.indicator.value[-shift - 1])
        vol = float(self.flat_trend.state[-shift + 1]) if shift > 1 else float(self.flat_trend.state[0])
        threshold = self._volatility_threshold()
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if value1 < value2:
            if value0 > value1 and vol >= threshold:
                buy_open = True
            sell_close = True
        if value1 > value2:
            if value0 < value1 and vol >= threshold:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.xlength) * 2 + 2, int(self.p.stdev_period) + int(self.p.stdev_length), int(self.p.atr_period) + int(self.p.atr_length)) + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.value[0])
        vol = float(self.flat_trend.state[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long value={value:.4f} vol={vol:.0f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell value={value:.4f} vol={vol:.0f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short value={value:.4f} vol={vol:.0f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy value={value:.4f} vol={vol:.0f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy value={value:.4f} vol={vol:.0f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell value={value:.4f} vol={vol:.0f}')
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
