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


class BrakeExpIndicator(bt.Indicator):
    lines = ('up_trend', 'down_trend', 'buy_signal', 'sell_signal')
    params = dict(a=3.0, b=1.0)

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
        a = float(self.p.a) * 0.1
        b = float(self.p.b) * 0.00001
        exp_val = (math.exp(bars_since_begin * a) - 1.0) * b
        value = self._begin_price + exp_val if self._is_long else self._begin_price - exp_val
        if self._is_long and value > float(self.data.low[0]):
            self._is_long = False
            self._begin_price = self._max_price
            self._begin_bar = len(self.data) - 1
            value = self._begin_price
            self._max_price = float('-inf')
            self._min_price = float('inf')
        elif (not self._is_long) and value < float(self.data.high[0]):
            self._is_long = True
            self._begin_price = self._min_price
            self._begin_bar = len(self.data) - 1
            value = self._begin_price
            self._max_price = float('-inf')
            self._min_price = float('inf')
        prev_up = float(self.lines.up_trend[-1]) if len(self) > 0 else 0.0
        prev_dn = float(self.lines.down_trend[-1]) if len(self) > 0 else 0.0
        if self._is_long:
            self.lines.up_trend[0] = value
            self.lines.down_trend[0] = 0.0
        else:
            self.lines.up_trend[0] = 0.0
            self.lines.down_trend[0] = value
        self.lines.buy_signal[0] = self.lines.down_trend[0] if prev_up > 0.0 and float(self.lines.down_trend[0]) > 0.0 else 0.0
        self.lines.sell_signal[0] = self.lines.up_trend[0] if prev_dn > 0.0 and float(self.lines.up_trend[0]) > 0.0 else 0.0


class BrakeExpStrategy(bt.Strategy):
    params = dict(a=3.0, b=1.0, signal_bar=1, lot=0.1)

    def __init__(self):
        self.indicator = BrakeExpIndicator(self.data, a=self.p.a, b=self.p.b)
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
        up_signal = float(self.indicator.buy_signal[-shift])
        dn_signal = float(self.indicator.sell_signal[-shift])
        up_trend = float(self.indicator.up_trend[-shift])
        dn_trend = float(self.indicator.down_trend[-shift])
        buy_open = up_signal != 0.0
        sell_open = dn_signal != 0.0
        sell_close = buy_open or (up_signal == 0.0 and up_trend != 0.0)
        buy_close = sell_open or (dn_signal == 0.0 and dn_trend != 0.0)
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        if len(self.data) < 6:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        up = float(self.indicator.up_trend[0])
        down = float(self.indicator.down_trend[0])
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
