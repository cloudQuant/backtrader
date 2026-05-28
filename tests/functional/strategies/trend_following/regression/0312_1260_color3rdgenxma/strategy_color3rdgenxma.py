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
    if price_mode in {'price_close', 'close'}:
        return data.close
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
    return (data.high + data.low + data.close) / 3.0


class Color3rdGenXMAIndicator(bt.Indicator):
    lines = ('value', 'color')
    params = dict(xma_method='ema', xlength=50, xphase=15, ipc='price_typical', price_shift=0)

    def __init__(self):
        price = resolve_price_line(self.data, self.p.ipc)
        ma_cls = resolve_ma_class(self.p.xma_method)
        slength = max(1, int(self.p.xlength) * 2)
        self._x1 = ma_cls(price, period=slength)
        self._x2 = ma_cls(self._x1, period=max(1, int(self.p.xlength)))
        lam = float(slength) / max(1.0, float(self.p.xlength))
        self._alpha = lam * (slength - 1.0) / max(1e-9, (slength - lam))
        self._dprice_shift = float(self.p.price_shift) * 0.00001
        value = (self._alpha + 1.0) * self._x1 - self._alpha * self._x2 + self._dprice_shift
        self.lines.value = value
        self.lines.color = bt.If(value > value(-1), 2.0, bt.If(value < value(-1), 0.0, 1.0))
        self.addminperiod(slength + int(self.p.xlength) + 5)


class Color3rdGenXMAStrategy(bt.Strategy):
    params = dict(
        start_hour=8,
        start_minute=0,
        time_min=720,
        xma_method='ema',
        xlength=50,
        xphase=15,
        ipc='price_typical',
        shift=0,
        price_shift=0,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = Color3rdGenXMAIndicator(
            self.data,
            xma_method=self.p.xma_method,
            xlength=self.p.xlength,
            xphase=self.p.xphase,
            ipc=self.p.ipc,
            price_shift=self.p.price_shift,
        )
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._entry_num = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _held_minutes(self):
        if not self.position:
            return 0.0
        entry_num = self._entry_num
        if entry_num is None:
            return 0.0
        current_num = self.data.datetime[0]
        return (current_num - entry_num) * 24.0 * 60.0

    def _indicator_signals(self):
        shift = max(1, int(self.p.signal_bar))
        color = int(self.indicator.color[-shift])
        buy_open1 = color == 2
        sell_open1 = color == 0
        buy_close = False
        sell_close = False
        return buy_open1, sell_open1, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.xlength) * 3 + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open1, sell_open1, buy_close, sell_close = self._indicator_signals()
        dt = bt.num2date(self.data.datetime[0])
        buy_open = buy_open1 and dt.hour == int(self.p.start_hour) and dt.minute == int(self.p.start_minute)
        sell_open = sell_open1 and dt.hour == int(self.p.start_hour) and dt.minute == int(self.p.start_minute)
        if self.position and self._held_minutes() >= float(self.p.time_min):
            buy_close = True
            sell_close = True
        color = int(self.indicator.color[0])
        value = float(self.indicator.value[0])
        if self.position:
            if self.position.size > 0:
                if buy_close:
                    self.log(f'close long color={color} value={value:.5f}')
                    self.close()
                    return
            if self.position.size < 0:
                if sell_close:
                    self.log(f'close short color={color} value={value:.5f}')
                    self.close()
                    return
        else:
            if buy_open1 and buy_open:
                self.log(f'buy color={color} value={value:.5f}')
                self.buy(size=self.p.lot)
                return
            if sell_open1 and sell_open:
                self.log(f'sell color={color} value={value:.5f}')
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            self._entry_num = self.data.datetime[0]
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
        self._entry_num = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
