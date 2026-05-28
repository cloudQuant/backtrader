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


class XMAIshimokuChannelIndicator(bt.Indicator):
    lines = ('mid', 'upper', 'lower',)
    params = dict(
        up_period=3,
        dn_period=3,
        up_mode='high',
        dn_mode='low',
        xma_method='sma',
        xlength=100,
        xphase=15,
        up_percent=1.0,
        dn_percent=1.0,
        price_shift=0,
    )

    def __init__(self):
        ma_cls = resolve_ma_class(self.p.xma_method)
        highest = bt.indicators.Highest(self.data.high, period=self.p.up_period)
        lowest = bt.indicators.Lowest(self.data.low, period=self.p.dn_period)
        midpoint = (highest + lowest) / 2.0
        self.lines.mid = ma_cls(midpoint, period=self.p.xlength) + self.p.price_shift
        self.lines.upper = self.lines.mid * (1.0 + self.p.up_percent / 100.0)
        self.lines.lower = self.lines.mid * (1.0 - self.p.dn_percent / 100.0)
        self.addminperiod(max(self.p.up_period, self.p.dn_period, self.p.xlength) + 3)


class XMAIshimokuChannelStrategy(bt.Strategy):
    params = dict(
        up_period=3,
        dn_period=3,
        up_mode='high',
        dn_mode='low',
        xma_method='sma',
        xlength=100,
        xphase=15,
        up_percent=1.0,
        dn_percent=1.0,
        price_shift=0,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.channel = XMAIshimokuChannelIndicator(
            self.data,
            up_period=self.p.up_period,
            dn_period=self.p.dn_period,
            up_mode=self.p.up_mode,
            dn_mode=self.p.dn_mode,
            xma_method=self.p.xma_method,
            xlength=self.p.xlength,
            xphase=self.p.xphase,
            up_percent=self.p.up_percent,
            dn_percent=self.p.dn_percent,
            price_shift=self.p.price_shift,
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
        close_prev = float(self.data.close[-shift])
        close_cur = float(self.data.close[-shift + 1]) if shift > 1 else float(self.data.close[0])
        up_prev = float(self.channel.upper[-shift])
        up_cur = float(self.channel.upper[-shift + 1]) if shift > 1 else float(self.channel.upper[0])
        dn_prev = float(self.channel.lower[-shift])
        dn_cur = float(self.channel.lower[-shift + 1]) if shift > 1 else float(self.channel.lower[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if close_prev > up_prev:
            if close_cur <= up_cur:
                buy_open = True
            sell_close = True
        if close_prev < dn_prev:
            if close_cur >= dn_cur:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.up_period), int(self.p.dn_period), int(self.p.xlength)) + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        upper = float(self.channel.upper[0])
        lower = float(self.channel.lower[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long upper={upper:.4f} lower={lower:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell upper={upper:.4f} lower={lower:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short upper={upper:.4f} lower={lower:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy upper={upper:.4f} lower={lower:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy upper={upper:.4f} lower={lower:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell upper={upper:.4f} lower={lower:.4f}')
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
