from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={'<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest'})
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5))


def _applied_price(data, price_type, ago=0):
    o = float(data.open[-ago])
    h = float(data.high[-ago])
    l = float(data.low[-ago])
    c = float(data.close[-ago])
    if price_type == 0:
        return c
    if price_type == 1:
        return o
    if price_type == 2:
        return h
    if price_type == 3:
        return l
    if price_type == 4:
        return (h + l) / 2.0
    if price_type == 5:
        return (h + l + c) / 3.0
    if price_type == 6:
        return (h + l + c + c) / 4.0
    return c


class VolumeWeightedMAIndicator(bt.Indicator):
    lines = ('vwma',)
    params = dict(length=12, ipc=0, use_tick_volume=True)

    def __init__(self):
        self.addminperiod(int(self.p.length) + 2)

    def next(self):
        length = int(self.p.length)
        weights = []
        total = 0.0
        for i in range(length):
            vol = float(self.data.volume[-i]) if self.p.use_tick_volume else float(self.data.openinterest[-i])
            if vol < 0:
                vol = 0.0
            weights.append(vol)
            total += vol
        if total == 0.0:
            self.lines.vwma[0] = _applied_price(self.data, int(self.p.ipc), 0)
            return
        value = 0.0
        for i in range(length):
            value += _applied_price(self.data, int(self.p.ipc), i) * (weights[i] / total)
        self.lines.vwma[0] = value


class ExpVolumeWeightedMAStrategy(bt.Strategy):
    params = dict(
        length=12,
        ipc=0,
        use_tick_volume=True,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = VolumeWeightedMAIndicator(self.signal_data, length=self.p.length, ipc=self.p.ipc, use_tick_volume=self.p.use_tick_volume)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def log(self, text):
        print(f'{bt.num2date(self.base.datetime[0]).isoformat()}, {text}')

    def _check_exit_levels(self):
        if not self.position:
            return False
        cp = float(self.base.close[0])
        pv = float(self.p.point)
        sd = self.p.stop_loss_points * pv if self.p.stop_loss_points > 0 else None
        td = self.p.take_profit_points * pv if self.p.take_profit_points > 0 else None
        ep = float(self.position.price)
        if self.position.size > 0:
            if sd and cp <= ep - sd:
                self.log(f'close long SL {cp:.2f}')
                self.close()
                return True
            if td and cp >= ep + td:
                self.log(f'close long TP {cp:.2f}')
                self.close()
                return True
        else:
            if sd and cp >= ep + sd:
                self.log(f'close short SL {cp:.2f}')
                self.close()
                return True
            if td and cp <= ep - td:
                self.log(f'close short TP {cp:.2f}')
                self.close()
                return True
        return False

    def _val(self, line, offset):
        v = float(line[-offset]) if offset else float(line[0])
        return 0.0 if math.isnan(v) else v

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return
        if self._check_exit_levels():
            return
        signal_bar = max(int(self.p.signal_bar) - 1, 0)
        min_needed = int(self.p.length) + signal_bar + 4
        if len(self.signal_data) < min_needed:
            return
        current_signal_len = len(self.signal_data)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        v0 = self._val(self.indicator.vwma, signal_bar)
        v1 = self._val(self.indicator.vwma, signal_bar + 1)
        v2 = self._val(self.indicator.vwma, signal_bar + 2)
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if v1 < v2:
            if self.p.buy_pos_open and v0 > v1:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True
        if v1 > v2:
            if self.p.sell_pos_open and v0 < v1:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True
        cp = float(self.base.close[0])
        sz = float(self.p.fixed_lot)
        if sz <= 0:
            return
        if sell_close and self.position.size < 0:
            self.log(f'close short signal {cp:.2f}')
            self.close()
        if buy_close and self.position.size > 0:
            self.log(f'close long signal {cp:.2f}')
            self.close()
        if buy_open:
            self.signal_count += 1
            self.log(f'buy signal {cp:.2f}')
            if self.position.size <= 0:
                self.buy(size=sz)
        if sell_open:
            self.signal_count += 1
            self.log(f'sell signal {cp:.2f}')
            if self.position.size >= 0:
                self.sell(size=sz)

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
