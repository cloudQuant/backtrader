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
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class ColorCoppockIndicator(bt.Indicator):
    lines = ('value', 'color')
    params = dict(
        roc1_period=14,
        roc2_period=10,
        xma_method='lwma',
        xma_period=12,
        xma_phase=100,
        applied_price='price_close',
    )

    def __init__(self):
        price_line = resolve_price_line(self.data, self.p.applied_price)
        roc1 = (price_line - price_line(-int(self.p.roc1_period))) / price_line(-int(self.p.roc1_period))
        roc2 = (price_line - price_line(-int(self.p.roc2_period))) / price_line(-int(self.p.roc2_period))
        self._roc_sum = roc1 + roc2
        ma_cls = resolve_ma_class(self.p.xma_method)
        self._smooth = ma_cls(self._roc_sum, period=max(1, int(self.p.xma_period)))
        self.addminperiod(max(int(self.p.roc1_period), int(self.p.roc2_period)) + int(self.p.xma_period) + 3)

    def next(self):
        value = float(self._smooth[0])
        prev = float(self._smooth[-1])
        self.lines.value[0] = value
        color = 2
        if value > 0:
            if value > prev:
                color = 4
            elif value < prev:
                color = 3
        if value < 0:
            if value < prev:
                color = 0
            elif value > prev:
                color = 1
        self.lines.color[0] = color

    def once(self, start, end):
        smooth = self._smooth.array
        value_line = self.lines.value.array
        color_line = self.lines.color.array
        for line in (value_line, color_line):
            while len(line) < end:
                line.append(float('nan'))

        actual_end = min(end, len(smooth))
        for i in range(start, actual_end):
            value = float(smooth[i])
            prev = float(smooth[i - 1]) if i > 0 else value
            color = 2
            if value > 0:
                if value > prev:
                    color = 4
                elif value < prev:
                    color = 3
            if value < 0:
                if value < prev:
                    color = 0
                elif value > prev:
                    color = 1
            value_line[i] = value
            color_line[i] = color


class ColorCoppockStrategy(bt.Strategy):
    params = dict(
        roc1_period=14,
        roc2_period=10,
        xma_method='lwma',
        xma_period=12,
        xma_phase=100,
        applied_price='price_close',
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = ColorCoppockIndicator(
            self.data,
            roc1_period=self.p.roc1_period,
            roc2_period=self.p.roc2_period,
            xma_method=self.p.xma_method,
            xma_period=self.p.xma_period,
            xma_phase=self.p.xma_phase,
            applied_price=self.p.applied_price,
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
        osc0 = float(self.indicator.value[-shift + 1]) if shift > 1 else float(self.indicator.value[0])
        osc1 = float(self.indicator.value[-shift])
        osc2 = float(self.indicator.value[-shift - 1])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if osc1 < osc2:
            if osc0 > osc1:
                buy_open = True
            sell_close = True
        if osc1 > osc2:
            if osc0 < osc1:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.roc1_period), int(self.p.roc2_period)) + int(self.p.xma_period) + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.value[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long value={value:.6f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell value={value:.6f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short value={value:.6f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy value={value:.6f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy value={value:.6f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell value={value:.6f}')
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
