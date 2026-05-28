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


class VininITrendIndicator(bt.Indicator):
    lines = ('trend',)
    params = dict(
        ma_method1='sma',
        length1=3,
        phase1=15,
        ma_step=10,
        ma_count=10,
        ma_method2='jjma',
        length2=20,
        phase2=100,
        ipc='price_close',
    )

    def __init__(self):
        price_line = resolve_price_line(self.data, self.p.ipc)
        periods = [int(self.p.length1 + idx * self.p.ma_step) for idx in range(int(self.p.ma_count))]
        self._ma_lines = [resolve_ma_class(self.p.ma_method1)(price_line, period=max(1, p)) for p in periods]
        self._smooth = resolve_ma_class(self.p.ma_method2)(self.lines.trend, period=max(1, int(self.p.length2)))
        self.addminperiod(max(periods) + int(self.p.length2) + 5)

    def next(self):
        close_value = float(self.data.close[0])
        score = 0
        for ma_line in self._ma_lines:
            if close_value > float(ma_line[0]):
                score += 1
            else:
                score -= 1
        raw = 100.0 * score / max(1, len(self._ma_lines))
        prev = float(self.lines.trend[-1]) if len(self) > 0 else raw
        if prev != prev:
            prev = raw
        period = max(1, int(self.p.length2))
        alpha = 2.0 / (period + 1.0)
        if len(self) == 0:
            self.lines.trend[0] = raw
        else:
            self.lines.trend[0] = alpha * raw + (1.0 - alpha) * prev

    def once(self, start, end):
        close_array = self.data.close.array
        ma_arrays = [ma_line.array for ma_line in self._ma_lines]
        trend_line = self.lines.trend.array
        while len(trend_line) < end:
            trend_line.append(float('nan'))

        period = max(1, int(self.p.length2))
        alpha = 2.0 / (period + 1.0)
        prev = None
        actual_end = min([end, len(close_array)] + [len(array) for array in ma_arrays])
        for i in range(start, actual_end):
            close_value = float(close_array[i])
            score = 0
            for ma_array in ma_arrays:
                if close_value > float(ma_array[i]):
                    score += 1
                else:
                    score -= 1
            raw = 100.0 * score / max(1, len(ma_arrays))
            value = raw if prev is None else alpha * raw + (1.0 - alpha) * prev
            trend_line[i] = value
            prev = value


class VininITrendStrategy(bt.Strategy):
    params = dict(
        mode='breakdown',
        ma_method1='sma',
        length1=3,
        phase1=15,
        ma_step=10,
        ma_count=10,
        ma_method2='jjma',
        length2=20,
        phase2=100,
        ipc='price_close',
        up_level=10,
        dn_level=-10,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = VininITrendIndicator(
            self.data,
            ma_method1=self.p.ma_method1,
            length1=self.p.length1,
            phase1=self.p.phase1,
            ma_step=self.p.ma_step,
            ma_count=self.p.ma_count,
            ma_method2=self.p.ma_method2,
            length2=self.p.length2,
            phase2=self.p.phase2,
            ipc=self.p.ipc,
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

    def _signals_breakdown(self, shift):
        value_prev = float(self.indicator.trend[-shift])
        value_cur = float(self.indicator.trend[-shift + 1]) if shift > 1 else float(self.indicator.trend[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if value_prev > float(self.p.up_level):
            if value_cur <= float(self.p.up_level):
                buy_open = True
            sell_close = True
        if value_prev < float(self.p.dn_level):
            if value_cur >= float(self.p.dn_level):
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def _signals_twist(self, shift):
        value0 = float(self.indicator.trend[-shift + 1]) if shift > 1 else float(self.indicator.trend[0])
        value1 = float(self.indicator.trend[-shift])
        value2 = float(self.indicator.trend[-shift - 1])
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

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        if str(self.p.mode).lower() == 'twist':
            return self._signals_twist(shift)
        return self._signals_breakdown(shift)

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.length1 + self.p.ma_step * (self.p.ma_count - 1)) + int(self.p.length2) + int(self.p.signal_bar) + 10
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.trend[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long trend={value:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell trend={value:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short trend={value:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy trend={value:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy trend={value:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell trend={value:.4f}')
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
