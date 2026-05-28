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
    return data.close


class BlauCMomentumIndicator(bt.Indicator):
    lines = ('value',)
    params = dict(
        xma_method='ema',
        xlength=1,
        xlength1=20,
        xlength2=5,
        xlength3=3,
        xphase=15,
        ipc1='price_close',
        ipc2='price_open',
    )

    def __init__(self):
        ma_cls = resolve_ma_class(self.p.xma_method)
        price1 = resolve_price_line(self.data, self.p.ipc1)
        price2 = resolve_price_line(self.data, self.p.ipc2)
        mom = price1 - price2(-max(0, int(self.p.xlength) - 1))
        xmom = ma_cls(mom, period=max(1, int(self.p.xlength1)))
        xxmom = ma_cls(xmom, period=max(1, int(self.p.xlength2)))
        xxxmom = ma_cls(xxmom, period=max(1, int(self.p.xlength3)))
        self._momentum = xxxmom
        self.lines.value = 100.0 * xxxmom
        self.addminperiod(int(self.p.xlength) + int(self.p.xlength1) + int(self.p.xlength2) + int(self.p.xlength3) + 5)


class BlauCMomentumStrategy(bt.Strategy):
    params = dict(
        mode='twist',
        xma_method='ema',
        xlength=1,
        xlength1=20,
        xlength2=5,
        xlength3=3,
        xphase=15,
        ipc1='price_close',
        ipc2='price_open',
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = BlauCMomentumIndicator(
            self.data,
            xma_method=self.p.xma_method,
            xlength=self.p.xlength,
            xlength1=self.p.xlength1,
            xlength2=self.p.xlength2,
            xlength3=self.p.xlength3,
            xphase=self.p.xphase,
            ipc1=self.p.ipc1,
            ipc2=self.p.ipc2,
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
        mode = str(self.p.mode).lower()
        buy_open = sell_open = buy_close = sell_close = False
        if mode == 'breakdown':
            v0 = float(self.indicator.value[-shift])
            v1 = float(self.indicator.value[-shift - 1])
            if v1 > 0:
                if v0 <= 0:
                    buy_open = True
                sell_close = True
            if v1 < 0:
                if v0 >= 0:
                    sell_open = True
                buy_close = True
        else:
            v0 = float(self.indicator.value[-shift])
            v1 = float(self.indicator.value[-shift - 1])
            v2 = float(self.indicator.value[-shift - 2])
            if v1 < v2:
                if v0 >= v1:
                    buy_open = True
                sell_close = True
            if v1 > v2:
                if v0 <= v1:
                    sell_open = True
                buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.xlength) + int(self.p.xlength1) + int(self.p.xlength2) + int(self.p.xlength3) + int(self.p.signal_bar) + 5
        if len(self.data) < warmup + 2:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.value[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long value={value:.2f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell value={value:.2f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short value={value:.2f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy value={value:.2f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy value={value:.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell value={value:.2f}')
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
