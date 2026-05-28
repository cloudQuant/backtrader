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


class FRASMAv2Indicator(bt.Indicator):
    lines = ('frasma', 'color')
    params = dict(e_period=30, normal_speed=20, ipc=0)

    def __init__(self):
        self.addminperiod(max(int(self.p.e_period), int(self.p.normal_speed)) + 3)

    def next(self):
        self.lines.color[0] = 1.0
        need = max(int(self.p.e_period), int(self.p.normal_speed))
        prices = [_applied_price(self.data, int(self.p.ipc), i) for i in range(min(need, len(self.data)))]
        e_period = int(self.p.e_period)
        normal_speed = int(self.p.normal_speed)
        g_period_minus_1 = e_period - 1
        if len(prices) < e_period:
            self.lines.frasma[0] = prices[0]
            return
        sample = prices[:e_period]
        price_max = max(sample)
        price_min = min(sample)
        price_range = price_max - price_min
        length = 0.0
        prior_diff = 0.0
        for k in range(g_period_minus_1 + 1):
            if price_range > 0.0:
                diff = (sample[k] - price_min) / price_range
                if k > 0:
                    length += math.sqrt((diff - prior_diff) ** 2 + (1.0 / (e_period ** 2)))
                prior_diff = diff
        if length > 0.0 and g_period_minus_1 > 0:
            fdi = 1.0 + (math.log(length) + math.log(2.0)) / math.log(2.0 * g_period_minus_1)
        else:
            fdi = 0.0
        res = 2.0 - fdi
        if res == 0.0:
            res = 2.0
        trail_dim = 1.0 / res
        alpha = trail_dim / 2.0
        speed = int(min(max(round(normal_speed * alpha), 1), 10000))
        speed = min(speed, len(prices))
        value = sum(prices[:speed]) / float(speed)
        self.lines.frasma[0] = value
        if len(self) < 2:
            return
        prev = float(self.lines.frasma[-1])
        color = 1.0
        if prev < value:
            color = 0.0
        if prev > value:
            color = 2.0
        self.lines.color[0] = color


class ExpFRASMAv2Strategy(bt.Strategy):
    params = dict(
        e_period=30,
        normal_speed=20,
        ipc=0,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=720,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = FRASMAv2Indicator(self.signal_data, e_period=self.p.e_period, normal_speed=self.p.normal_speed, ipc=self.p.ipc)
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
        min_needed = max(int(self.p.e_period), int(self.p.normal_speed)) + signal_bar + 4
        if len(self.signal_data) < min_needed:
            return
        current_signal_len = len(self.signal_data)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        c0 = self._val(self.indicator.color, signal_bar)
        c1 = self._val(self.indicator.color, signal_bar + 1)
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if c1 == 0.0:
            if self.p.buy_pos_open and c0 > 0.0:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True
        if c1 == 2.0:
            if self.p.sell_pos_open and c0 < 2.0:
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
