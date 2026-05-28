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
        return (data.high + data.low + data.close + data.close) / 4.0
    if price_mode in {'price_simpl', 'simpl'}:
        return (data.open + data.close) / 2.0
    if price_mode in {'price_quarter', 'quarter'}:
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class KAMAIndicator(bt.Indicator):
    lines = ('ama',)
    params = dict(period=9, fast_period=2, slow_period=30, power=2.0)

    def __init__(self):
        self.addminperiod(max(self.p.period, self.p.slow_period) + 2)

    def next(self):
        period = int(self.p.period)
        current = float(self.data[0])
        prev = float(self.lines.ama[-1]) if len(self) > 0 else current
        if not math.isfinite(prev):
            prev = 0.0
        if not math.isfinite(current):
            self.lines.ama[0] = prev
            return
        if len(self.data) <= period:
            self.lines.ama[0] = current
            return
        change = abs(float(self.data[0]) - float(self.data[-period]))
        volatility = 0.0
        for i in range(period):
            left = float(self.data[-i])
            right = float(self.data[-i - 1])
            if math.isfinite(left) and math.isfinite(right):
                volatility += abs(left - right)
        er = (change / volatility) if volatility else 0.0
        fast_sc = 2.0 / (int(self.p.fast_period) + 1.0)
        slow_sc = 2.0 / (int(self.p.slow_period) + 1.0)
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** float(self.p.power)
        self.lines.ama[0] = prev + sc * (current - prev)

    def once(self, start, end):
        period = int(self.p.period)
        src = self.data.array
        dst = self.lines.ama.array
        fast_sc = 2.0 / (int(self.p.fast_period) + 1.0)
        slow_sc = 2.0 / (int(self.p.slow_period) + 1.0)
        power = float(self.p.power)
        for i in range(start, end):
            current = float(src[i])
            prev = float(dst[i - 1]) if i > 0 else current
            if not math.isfinite(prev):
                prev = 0.0
            if not math.isfinite(current):
                dst[i] = prev
                continue
            if i <= period:
                dst[i] = current
                continue
            change = abs(current - float(src[i - period]))
            volatility = 0.0
            for j in range(period):
                left = float(src[i - j])
                right = float(src[i - j - 1])
                if math.isfinite(left) and math.isfinite(right):
                    volatility += abs(left - right)
            er = (change / volatility) if volatility else 0.0
            sc = (er * (fast_sc - slow_sc) + slow_sc) ** power
            dst[i] = prev + sc * (current - prev)


class ColorMomentumAMAIndicator(bt.Indicator):
    lines = ('value',)
    params = dict(
        alength=8,
        ama_period=9,
        fast_ma_period=2,
        slow_ma_period=30,
        ipc='price_close',
        g=2.0,
    )

    def __init__(self):
        price_line = resolve_price_line(self.data, self.p.ipc)
        momentum = price_line - price_line(-int(self.p.alength))
        self.lines.value = bt.indicators.ExponentialMovingAverage(
            momentum,
            period=max(1, int(self.p.ama_period)),
        )
        self.addminperiod(int(self.p.alength) + int(self.p.ama_period) + 5)


class ColorMomentumAMAStrategy(bt.Strategy):
    params = dict(
        alength=8,
        ama_period=9,
        fast_ma_period=2,
        slow_ma_period=30,
        ipc='price_close',
        g=2.0,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = ColorMomentumAMAIndicator(
            self.data,
            alength=self.p.alength,
            ama_period=self.p.ama_period,
            fast_ma_period=self.p.fast_ma_period,
            slow_ma_period=self.p.slow_ma_period,
            ipc=self.p.ipc,
            g=self.p.g,
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
        value0 = float(self.indicator.value[-shift + 1]) if shift > 1 else float(self.indicator.value[0])
        value1 = float(self.indicator.value[-shift])
        value2 = float(self.indicator.value[-shift - 1])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if value1 < value2:
            if value0 > value1:
                buy_open = True
            sell_close = True
        if value1 > value2:
            if value0 < value1:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.alength) + int(self.p.ama_period) + int(self.p.signal_bar) + 10
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.value[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long value={value:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell value={value:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short value={value:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy value={value:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy value={value:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell value={value:.4f}')
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
