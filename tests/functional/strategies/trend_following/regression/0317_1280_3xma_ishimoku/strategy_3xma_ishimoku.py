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


class XMAIshimokuLine(bt.Indicator):
    lines = ('xma',)
    params = dict(
        up_period=3,
        dn_period=3,
        xma_method='sma',
        xlength=8,
        xphase=15,
    )

    def __init__(self):
        highest = bt.indicators.Highest(self.data.high, period=self.p.up_period)
        lowest = bt.indicators.Lowest(self.data.low, period=self.p.dn_period)
        midpoint = (highest + lowest) / 2.0
        ma_cls = resolve_ma_class(self.p.xma_method)
        self.lines.xma = ma_cls(midpoint, period=self.p.xlength)
        self.addminperiod(max(self.p.up_period, self.p.dn_period, self.p.xlength) + 3)


class ThreeXMAIshimokuStrategy(bt.Strategy):
    params = dict(
        up_period1=3,
        dn_period1=3,
        up_period2=6,
        dn_period2=6,
        up_period3=9,
        dn_period3=9,
        xma1_method='sma',
        xma2_method='sma',
        xma3_method='sma',
        xlength1=8,
        xlength2=25,
        xlength3=80,
        xphase=15,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.fast = XMAIshimokuLine(
            self.data,
            up_period=self.p.up_period1,
            dn_period=self.p.dn_period1,
            xma_method=self.p.xma1_method,
            xlength=self.p.xlength1,
            xphase=self.p.xphase,
        )
        self.mid = XMAIshimokuLine(
            self.data,
            up_period=self.p.up_period2,
            dn_period=self.p.dn_period2,
            xma_method=self.p.xma2_method,
            xlength=self.p.xlength2,
            xphase=self.p.xphase,
        )
        self.slow = XMAIshimokuLine(
            self.data,
            up_period=self.p.up_period3,
            dn_period=self.p.dn_period3,
            xma_method=self.p.xma3_method,
            xlength=self.p.xlength3,
            xphase=self.p.xphase,
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
        fast_prev = float(self.fast.xma[-shift])
        fast_cur = float(self.fast.xma[-shift + 1]) if shift > 1 else float(self.fast.xma[0])
        up_prev = max(float(self.mid.xma[-shift]), float(self.slow.xma[-shift]))
        up_cur = max(
            float(self.mid.xma[-shift + 1]) if shift > 1 else float(self.mid.xma[0]),
            float(self.slow.xma[-shift + 1]) if shift > 1 else float(self.slow.xma[0]),
        )
        dn_prev = min(float(self.mid.xma[-shift]), float(self.slow.xma[-shift]))
        dn_cur = min(
            float(self.mid.xma[-shift + 1]) if shift > 1 else float(self.mid.xma[0]),
            float(self.slow.xma[-shift + 1]) if shift > 1 else float(self.slow.xma[0]),
        )
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if fast_prev > up_prev:
            if fast_cur <= up_cur:
                buy_open = True
            sell_close = True
        if fast_prev < dn_prev:
            if fast_cur >= dn_cur:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.xlength1), int(self.p.xlength2), int(self.p.xlength3)) + int(self.p.signal_bar) + 10
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        fast = float(self.fast.xma[0])
        upper = max(float(self.mid.xma[0]), float(self.slow.xma[0]))
        lower = min(float(self.mid.xma[0]), float(self.slow.xma[0]))
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long fast={fast:.4f} upper={upper:.4f} lower={lower:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell fast={fast:.4f} upper={upper:.4f} lower={lower:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short fast={fast:.4f} upper={upper:.4f} lower={lower:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy fast={fast:.4f} upper={upper:.4f} lower={lower:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy fast={fast:.4f} upper={upper:.4f} lower={lower:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell fast={fast:.4f} upper={upper:.4f} lower={lower:.4f}')
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
