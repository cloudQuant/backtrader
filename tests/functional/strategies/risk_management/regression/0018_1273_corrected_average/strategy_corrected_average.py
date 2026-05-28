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
        return bt.indicators.SimpleMovingAverage
    if mode in {'ema', 'mode_ema'}:
        return bt.indicators.ExponentialMovingAverage
    if mode in {'smma', 'mode_smma'}:
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
        return (data.high + data.low + data.close + data.close) / 4.0
    return data.close


class CorrectedAverageIndicator(bt.Indicator):
    lines = ('corrected',)
    params = dict(ma_method='sma', length=12, applied_price='price_close')

    def __init__(self):
        price_line = resolve_price_line(self.data, self.p.applied_price)
        self._ma = resolve_ma_class(self.p.ma_method)(price_line, period=self.p.length)
        self._std = bt.indicators.StandardDeviation(price_line, period=self.p.length)
        self.addminperiod(int(self.p.length) + 3)

    def next(self):
        ma = float(self._ma[0])
        std = float(self._std[0])
        prev = float(self.lines.corrected[-1]) if len(self) > 0 else ma
        if prev != prev:
            prev = ma
        v1 = std ** 2
        v2 = (prev - ma) ** 2
        if v2 < v1 or v2 == 0:
            k = 0.0
        else:
            k = 1.0 - v1 / v2
        self.lines.corrected[0] = prev + k * (ma - prev)

    def once(self, start, end):
        ma_array = self._ma.array
        std_array = self._std.array
        corrected_line = self.lines.corrected.array
        while len(corrected_line) < end:
            corrected_line.append(float('nan'))

        prev = None
        actual_end = min(end, len(ma_array), len(std_array))
        for i in range(start, actual_end):
            ma = float(ma_array[i])
            std = float(std_array[i])
            previous = ma if prev is None else prev
            v1 = std ** 2
            v2 = (previous - ma) ** 2
            if v2 < v1 or v2 == 0:
                k = 0.0
            else:
                k = 1.0 - v1 / v2
            value = previous + k * (ma - previous)
            corrected_line[i] = value
            prev = value


class CorrectedAverageStrategy(bt.Strategy):
    params = dict(
        ma_method='sma',
        length=12,
        applied_price='price_close',
        level=300,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = CorrectedAverageIndicator(
            self.data,
            ma_method=self.p.ma_method,
            length=self.p.length,
            applied_price=self.p.applied_price,
        )
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._level = float(self.p.level) * 0.01

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        close_prev = float(self.data.close[-shift])
        close_cur = float(self.data.close[-shift + 1]) if shift > 1 else float(self.data.close[0])
        value_prev = float(self.indicator.corrected[-shift])
        value_cur = float(self.indicator.corrected[-shift + 1]) if shift > 1 else float(self.indicator.corrected[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if close_prev > value_prev + self._level:
            if close_cur <= value_cur + self._level:
                buy_open = True
            sell_close = True
        if close_prev < value_prev - self._level:
            if close_cur >= value_cur - self._level:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.length) + int(self.p.signal_bar) + 10
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.corrected[0])
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
