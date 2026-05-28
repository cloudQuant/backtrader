from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
LOCAL_BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(LOCAL_BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(LOCAL_BACKTRADER_REPO))

import backtrader as bt


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=15):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
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


def resample_to_h4(df):
    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'sum',
    }
    h4 = df.resample('4h', label='right', closed='right').agg(agg)
    h4 = h4.dropna(subset=['open', 'high', 'low', 'close'])
    return h4


def build_finetuning_weights(ftma, rank1, rank2, rank3, shift1, shift2, shift3):
    weights = np.zeros(ftma, dtype=float)
    total = 0.0
    for h in range(ftma):
        x = h / (ftma - 1.0)
        value = shift1 + np.power(x, rank1) * (1.0 - shift1)
        value = (shift2 + np.power(1.0 - x, rank2) * (1.0 - shift2)) * value
        if x < 0.5:
            value = (shift3 + np.power(1.0 - x * 2.0, rank3) * (1.0 - shift3)) * value
        else:
            value = (shift3 + np.power(x * 2.0 - 1.0, rank3) * (1.0 - shift3)) * value
        weights[h] = value
        total += value
    if total == 0:
        return weights
    return weights / total


def compute_finetuning_state(df, ftma, rank1, rank2, rank3, shift1, shift2, shift3, gap):
    weights = build_finetuning_weights(ftma, rank1, rank2, rank3, shift1, shift2, shift3)
    opens = df['open'].to_numpy(dtype=float)
    highs = df['high'].to_numpy(dtype=float)
    lows = df['low'].to_numpy(dtype=float)
    closes = df['close'].to_numpy(dtype=float)
    ext_open = np.full(len(df), np.nan, dtype=float)
    ext_high = np.full(len(df), np.nan, dtype=float)
    ext_low = np.full(len(df), np.nan, dtype=float)
    ext_close = np.full(len(df), np.nan, dtype=float)
    state = np.full(len(df), np.nan, dtype=float)
    start = ftma + 1
    for bar in range(start, len(df)):
        o = 0.0
        h = 0.0
        l = 0.0
        c = 0.0
        for index in range(ftma):
            weight = weights[index]
            o += weight * opens[bar - index]
            h += weight * highs[bar - index]
            l += weight * lows[bar - index]
            c += weight * closes[bar - index]
        max_value = max(o, c, l, h)
        min_value = min(o, c, l, h)
        ext_open[bar] = o
        ext_high[bar] = max_value
        ext_low[bar] = min_value
        ext_close[bar] = c
        if abs(opens[bar] - closes[bar]) <= gap:
            prev_index = max(bar - 1, 0)
            if np.isnan(ext_close[prev_index]):
                ext_open[bar] = ext_close[bar]
            else:
                ext_open[bar] = ext_close[prev_index]
        if ext_open[bar] < ext_close[bar]:
            state[bar] = 2.0
        elif ext_open[bar] > ext_close[bar]:
            state[bar] = 0.0
        else:
            state[bar] = 1.0
    result = df.copy()
    result['state'] = state
    return result.dropna(subset=['state'])


def build_signal_frame(
    filepath,
    fromdate=None,
    todate=None,
    bar_shift_minutes=15,
    long_params=None,
    short_params=None,
):
    base = load_mt5_csv(filepath, fromdate=fromdate, todate=todate, bar_shift_minutes=bar_shift_minutes)
    h4 = resample_to_h4(base)
    long_state = compute_finetuning_state(h4, **long_params)[['state']].rename(columns={'state': 'long_state'})
    short_state = compute_finetuning_state(h4, **short_params)[['state']].rename(columns={'state': 'short_state'})
    frame = h4.join(long_state, how='left').join(short_state, how='left')
    frame = frame.dropna(subset=['long_state', 'short_state'])
    return frame


class FineTuningFeed(bt.feeds.PandasData):
    lines = ('long_state', 'short_state',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('long_state', 6),
        ('short_state', 7),
    )


class ExpFineTuningMACandleDuplexStrategy(bt.Strategy):
    params = dict(
        point=0.01,
        long_pos_open=True,
        long_pos_close=True,
        long_lot=0.1,
        long_stop_loss_points=1000,
        long_take_profit_points=2000,
        short_pos_open=True,
        short_pos_close=True,
        short_lot=0.1,
        short_stop_loss_points=1000,
        short_take_profit_points=2000,
        long_indicator={'ftma': 10, 'rank1': 2.0, 'rank2': 2.0, 'rank3': 2.0, 'shift1': 1.0, 'shift2': 1.0, 'shift3': 1.0, 'gap': 10},
        short_indicator={'ftma': 10, 'rank1': 2.0, 'rank2': 2.0, 'rank3': 2.0, 'shift1': 1.0, 'shift2': 1.0, 'shift3': 1.0, 'gap': 10},
    )

    def __init__(self):
        self.long_data = self.datas[0]
        self.short_data = self.datas[1]
        self.orders = {self.long_data: None, self.short_data: None}
        self.stop_levels = {self.long_data: None, self.short_data: None}
        self.take_profit_levels = {self.long_data: None, self.short_data: None}
        self.bar_num = 0
        self.long_entries = 0
        self.short_entries = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.long_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pending(self):
        return any(order is not None for order in self.orders.values())

    def _clear_levels(self, data):
        self.stop_levels[data] = None
        self.take_profit_levels[data] = None

    def _set_long_levels(self, price):
        self.stop_levels[self.long_data] = price - self.p.long_stop_loss_points * self.p.point if self.p.long_stop_loss_points else None
        self.take_profit_levels[self.long_data] = price + self.p.long_take_profit_points * self.p.point if self.p.long_take_profit_points else None

    def _set_short_levels(self, price):
        self.stop_levels[self.short_data] = price + self.p.short_stop_loss_points * self.p.point if self.p.short_stop_loss_points else None
        self.take_profit_levels[self.short_data] = price - self.p.short_take_profit_points * self.p.point if self.p.short_take_profit_points else None

    def _check_long_exit_levels(self):
        pos = self.getposition(self.long_data)
        if not pos.size:
            return False
        low = float(self.long_data.low[-1])
        high = float(self.long_data.high[-1])
        stop = self.stop_levels[self.long_data]
        take = self.take_profit_levels[self.long_data]
        if stop is not None and low <= stop:
            self.log(f'close long stop={stop:.2f}')
            self.orders[self.long_data] = self.close(data=self.long_data)
            return True
        if take is not None and high >= take:
            self.log(f'close long take_profit={take:.2f}')
            self.orders[self.long_data] = self.close(data=self.long_data)
            return True
        return False

    def _check_short_exit_levels(self):
        pos = self.getposition(self.short_data)
        if not pos.size:
            return False
        low = float(self.short_data.low[-1])
        high = float(self.short_data.high[-1])
        stop = self.stop_levels[self.short_data]
        take = self.take_profit_levels[self.short_data]
        if stop is not None and high >= stop:
            self.log(f'close short stop={stop:.2f}')
            self.orders[self.short_data] = self.close(data=self.short_data)
            return True
        if take is not None and low <= take:
            self.log(f'close short take_profit={take:.2f}')
            self.orders[self.short_data] = self.close(data=self.short_data)
            return True
        return False

    def next(self):
        self.bar_num += 1

    def next_open(self):
        if self._pending():
            return
        if len(self.long_data) < 3 or len(self.short_data) < 3:
            return

        if self._check_long_exit_levels() or self._check_short_exit_levels():
            return

        long_prev = float(self.long_data.long_state[-1])
        long_prev2 = float(self.long_data.long_state[-2])
        short_prev = float(self.short_data.short_state[-1])
        short_prev2 = float(self.short_data.short_state[-2])

        buy_open = self.p.long_pos_open and long_prev == 2.0 and long_prev2 != 2.0
        buy_close = self.p.long_pos_close and long_prev == 0.0
        sell_open = self.p.short_pos_open and short_prev == 0.0 and short_prev2 != 0.0
        sell_close = self.p.short_pos_close and short_prev == 2.0

        if self.getposition(self.long_data).size > 0 and buy_close:
            self.log(f'close long state={long_prev:.0f}')
            self.orders[self.long_data] = self.close(data=self.long_data)

        if self.getposition(self.short_data).size < 0 and sell_close:
            self.log(f'close short state={short_prev:.0f}')
            self.orders[self.short_data] = self.close(data=self.short_data)

        if self._pending():
            return

        if self.getposition(self.long_data).size == 0 and buy_open:
            self.log(f'buy size={self.p.long_lot:.2f} state={long_prev:.0f}')
            self.orders[self.long_data] = self.buy(data=self.long_data, size=self.p.long_lot)

        if self.getposition(self.short_data).size == 0 and sell_open:
            self.log(f'sell size={self.p.short_lot:.2f} state={short_prev:.0f}')
            self.orders[self.short_data] = self.sell(data=self.short_data, size=self.p.short_lot)

    def notify_order(self, order):
        data = order.data
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            pos = self.getposition(data).size
            if data is self.long_data:
                if order.isbuy() and pos > 0:
                    self.long_entries += 1
                    self._set_long_levels(order.executed.price)
                elif pos == 0:
                    self._clear_levels(data)
            elif data is self.short_data:
                if order.issell() and pos < 0:
                    self.short_entries += 1
                    self._set_short_levels(order.executed.price)
                elif pos == 0:
                    self._clear_levels(data)
        self.orders[data] = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        side = 'long' if trade.data is self.long_data else 'short'
        self.log(f'{side} trade closed pnl={trade.pnlcomm:.2f}')
