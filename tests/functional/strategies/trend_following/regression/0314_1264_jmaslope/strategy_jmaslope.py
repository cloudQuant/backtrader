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
        return (2.0 * data.close + data.high + data.low) / 4.0
    if price_mode in {'price_simpl', 'simpl'}:
        return (data.open + data.close) / 2.0
    if price_mode in {'price_quarter', 'quarter'}:
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class JMASlopeIndicator(bt.Indicator):
    lines = ('value', 'color')
    params = dict(jlength=14, jphase=0, ipc='price_close')

    def __init__(self):
        price_line = resolve_price_line(self.data, self.p.ipc)
        self._jma = bt.indicators.ExponentialMovingAverage(price_line, period=max(1, int(self.p.jlength)))
        delta = self._jma - self._jma(-1)
        self.lines.value = delta
        self.lines.color = bt.If(delta > 0.0, 4.0, bt.If(delta < 0.0, 0.0, 2.0))
        self.addminperiod(32 + int(self.p.jlength))


class JMASlopeStrategy(bt.Strategy):
    params = dict(
        mode='breakdown',
        jlength=14,
        jphase=0,
        ipc='price_close',
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = JMASlopeIndicator(self.data, jlength=self.p.jlength, jphase=self.p.jphase, ipc=self.p.ipc)
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
        value_prev = float(self.indicator.value[-shift])
        value_cur = float(self.indicator.value[-shift + 1]) if shift > 1 else float(self.indicator.value[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if value_prev > 0:
            if value_cur <= 0:
                buy_open = True
            sell_close = True
        if value_prev < 0:
            if value_cur >= 0:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def _signals_twist(self, shift):
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

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        if str(self.p.mode).lower() == 'twist':
            return self._signals_twist(shift)
        return self._signals_breakdown(shift)

    def next(self):
        self.bar_num += 1
        warmup = 32 + int(self.p.jlength) + int(self.p.signal_bar) + 5
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
