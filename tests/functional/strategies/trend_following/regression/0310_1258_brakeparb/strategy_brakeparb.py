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


class BrakeParbIndicator(bt.Indicator):
    lines = ('buy', 'sell', 'up', 'down')
    params = dict(a=1.5, b=1.0, bigin_shift=10.0)

    def __init__(self):
        self.addminperiod(5)
        self._is_long = True
        self._max_price = float('-inf')
        self._min_price = float('inf')
        self._begin_bar = 0
        self._begin_price = None

    def next(self):
        if self._begin_price is None:
            self._begin_price = float(self.data.low[0])
        self._max_price = max(self._max_price, float(self.data.high[0]))
        self._min_price = min(self._min_price, float(self.data.low[0]))
        bars_since_begin = max(0, len(self.data) - 1 - self._begin_bar)
        b = float(self.p.b) * 0.00001 * 15.0
        bigin_shift = float(self.p.bigin_shift) * 0.00001
        parab = math.pow(max(0.0, float(bars_since_begin)), float(self.p.a)) * b
        value = self._begin_price + parab if self._is_long else self._begin_price - parab
        if self._is_long and value > float(self.data.low[0]):
            self._is_long = False
            self._begin_price = self._max_price + bigin_shift
            self._begin_bar = len(self.data) - 1
            value = self._begin_price
            self._max_price = float('-inf')
            self._min_price = float('inf')
        elif (not self._is_long) and value < float(self.data.high[0]):
            self._is_long = True
            self._begin_price = self._min_price - bigin_shift
            self._begin_bar = len(self.data) - 1
            value = self._begin_price
            self._max_price = float('-inf')
            self._min_price = float('inf')
        prev_up = float(self.lines.up[-1]) if len(self) > 0 else 0.0
        prev_dn = float(self.lines.down[-1]) if len(self) > 0 else 0.0
        if self._is_long:
            self.lines.up[0] = value
            self.lines.down[0] = 0.0
        else:
            self.lines.up[0] = 0.0
            self.lines.down[0] = value
        self.lines.buy[0] = self.lines.down[0] if prev_up > 0.0 and float(self.lines.down[0]) > 0.0 else 0.0
        self.lines.sell[0] = self.lines.up[0] if prev_dn > 0.0 and float(self.lines.up[0]) > 0.0 else 0.0


class BrakeParbStrategy(bt.Strategy):
    params = dict(a=1.5, b=1.0, bigin_shift=10.0, signal_bar=1, lot=0.1)

    def __init__(self):
        self.indicator = BrakeParbIndicator(self.data, a=self.p.a, b=self.p.b, bigin_shift=self.p.bigin_shift)
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
        up_value = float(self.indicator.buy[-shift])
        dn_value = float(self.indicator.sell[-shift])
        buy_open = up_value != 0.0
        sell_open = dn_value != 0.0
        buy_close = sell_open
        sell_close = buy_open
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        if len(self.data) < 6:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        up = float(self.indicator.up[0])
        down = float(self.indicator.down[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long up={up:.5f} down={down:.5f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell up={up:.5f} down={down:.5f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short up={up:.5f} down={down:.5f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy up={up:.5f} down={down:.5f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy up={up:.5f} down={down:.5f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell up={up:.5f} down={down:.5f}')
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
