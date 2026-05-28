from __future__ import absolute_import, division, print_function, unicode_literals

import io
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


class VWMADigitSystem(bt.Indicator):
    lines = ('color',)
    params = dict(length=12, digit=2, shift=2, use_tick_volume=True, point=0.01)

    def __init__(self):
        self.addminperiod(int(self.p.length) + int(self.p.shift) + 3)

    def _weighted_level(self, series_name, ago=0):
        length = int(self.p.length)
        weights = []
        total = 0.0
        for i in range(length):
            idx = ago + i
            vol = float(self.data.volume[-idx]) if self.p.use_tick_volume else float(self.data.openinterest[-idx])
            weights.append(max(vol, 0.0))
            total += max(vol, 0.0)
        if total == 0.0:
            return float(getattr(self.data, series_name)[-ago])
        value = 0.0
        for i in range(length):
            idx = ago + i
            value += float(getattr(self.data, series_name)[-idx]) * (weights[i] / total)
        step = float(self.p.point) * (10 ** int(self.p.digit))
        return round(value / step) * step if step else value

    def next(self):
        shift = int(self.p.shift)
        up = self._weighted_level('high', shift)
        dn = self._weighted_level('low', shift)
        close = float(self.data.close[0])
        open_ = float(self.data.open[0])
        color = 2.0
        if close > up:
            color = 4.0 if open_ < close else 3.0
        if close < dn:
            color = 0.0 if open_ > close else 1.0
        self.lines.color[0] = color


class ExpVWMADigitSystemStrategy(bt.Strategy):
    params = dict(
        length=12,
        digit=2,
        shift=2,
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
        self.ind = VWMADigitSystem(self.signal_data, length=self.p.length, digit=self.p.digit, shift=self.p.shift, use_tick_volume=self.p.use_tick_volume, point=self.p.point)
        self.bar_num = 0
        self.signal_count = 0
        self.trade_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def _check_exit_levels(self):
        if not self.position:
            return False
        cp = float(self.base.close[0])
        pv = float(self.p.point)
        sd = self.p.stop_loss_points * pv
        td = self.p.take_profit_points * pv
        ep = float(self.position.price)
        if self.position.size > 0 and (cp <= ep - sd or cp >= ep + td):
            self.close()
            return True
        if self.position.size < 0 and (cp >= ep + sd or cp <= ep - td):
            self.close()
            return True
        return False

    def next(self):
        self.bar_num += 1
        if self._check_exit_levels():
            return
        sb = max(int(self.p.signal_bar) - 1, 0)
        if len(self.signal_data) < int(self.p.length) + int(self.p.shift) + sb + 4:
            return
        if len(self.signal_data) == self._last_signal_len:
            return
        self._last_signal_len = len(self.signal_data)
        c0 = float(self.ind.color[-sb]) if sb else float(self.ind.color[0])
        c1 = float(self.ind.color[-(sb + 1)])
        buy_open = c1 > 2.0 and c0 < 3.0 and self.p.buy_pos_open
        sell_open = c1 < 2.0 and c0 > 1.0 and self.p.sell_pos_open
        buy_close = sell_open and self.p.buy_pos_close
        sell_close = buy_open and self.p.sell_pos_close
        if sell_close and self.position.size < 0:
            self.close()
        if buy_close and self.position.size > 0:
            self.close()
        if buy_open and self.position.size <= 0:
            self.signal_count += 1
            self.buy(size=float(self.p.fixed_lot))
        if sell_open and self.position.size >= 0:
            self.signal_count += 1
            self.sell(size=float(self.p.fixed_lot))

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
