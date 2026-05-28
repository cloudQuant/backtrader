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
    if price_mode in {'price_trendfollow0', 'trendfollow0'}:
        return (data.high + data.low + data.close + data.close) / 4.0
    if price_mode in {'price_trendfollow1', 'trendfollow1'}:
        return (data.high + data.low + data.close + data.open + data.close) / 5.0
    return data.close


class ZPFIndicator(bt.Indicator):
    lines = ('line1', 'line2', 'zpf',)
    params = dict(
        xma_method='sma',
        xlength=12,
        xphase=15,
        ipc='price_close',
        volume_type='tick',
    )

    def __init__(self):
        ma_cls = resolve_ma_class(self.p.xma_method)
        price_line = resolve_price_line(self.data, self.p.ipc)
        volume_line = self.data.volume if str(self.p.volume_type).lower() == 'tick' else self.data.openinterest
        self.x1ma = ma_cls(price_line, period=self.p.xlength)
        self.x2ma = ma_cls(price_line, period=max(1, 2 * self.p.xlength))
        self.xvol = ma_cls(volume_line, period=self.p.xlength)
        self.lines.zpf = self.xvol * (self.x1ma - self.x2ma) / 2.0
        self.lines.line1 = -self.lines.zpf
        self.lines.line2 = self.lines.zpf
        self.addminperiod(max(2 * self.p.xlength, self.p.xlength) + 2)


class ZPFStrategy(bt.Strategy):
    params = dict(
        xma_method='sma',
        xlength=12,
        xphase=15,
        ipc='price_close',
        volume_type='tick',
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.zpf = ZPFIndicator(
            self.data,
            xma_method=self.p.xma_method,
            xlength=self.p.xlength,
            xphase=self.p.xphase,
            ipc=self.p.ipc,
            volume_type=self.p.volume_type,
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
        current = float(self.zpf.line2[-shift])
        previous = float(self.zpf.line2[-shift - 1])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if previous > 0:
            if current <= 0:
                buy_open = True
            sell_close = True
        if previous < 0:
            if current >= 0:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(2 * int(self.p.xlength), int(self.p.signal_bar)) + 5:
            return

        buy_open, sell_open, buy_close, sell_close = self._signals()
        zpf_value = float(self.zpf.line2[0])

        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long zpf={zpf_value:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell zpf={zpf_value:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short zpf={zpf_value:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy zpf={zpf_value:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy zpf={zpf_value:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell zpf={zpf_value:.4f}')
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
