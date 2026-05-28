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
import backtrader.feeds as btfeeds
import pandas as pd



def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df



def resample_ohlcv(df, rule):
    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
        'spread': 'last',
    }
    out = df.resample(rule, label='right', closed='right').agg(agg).dropna()
    return out


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class SpearmanRankCorrelationHistogram(bt.Indicator):
    lines = ('value', 'color')
    params = dict(range_n=14, direction=True, in_high_level=0.5, in_low_level=-0.5)

    def __init__(self):
        self.addminperiod(int(self.p.range_n) + 2)

    def _ranks(self, values):
        indexed = list(enumerate(values))
        sorted_values = sorted(indexed, key=lambda item: item[1], reverse=bool(self.p.direction))
        ranks = [0.0] * len(values)
        i = 0
        while i < len(sorted_values):
            j = i + 1
            while j < len(sorted_values) and sorted_values[j][1] == sorted_values[i][1]:
                j += 1
            avg_rank = (i + 1 + j) / 2.0
            for k in range(i, j):
                ranks[sorted_values[k][0]] = avg_rank
            i = j
        return ranks

    def next(self):
        n = int(self.p.range_n)
        values = [int(round(float(self.data.close[-i]) * 100.0)) for i in range(n)]
        ranks = self._ranks(values)
        z2 = 0.0
        for i, rank in enumerate(ranks):
            z2 += (rank - (i + 1)) ** 2
        res = 1.0 - 6.0 * z2 / (n ** 3 - n)
        self.lines.value[0] = res
        clr = 2
        if res > 0:
            clr = 4 if res > float(self.p.in_high_level) else 3
        elif res < 0:
            clr = 0 if res < float(self.p.in_low_level) else 1
        self.lines.color[0] = clr


class ExpSpearmanRankCorrelationHistogramStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        stop_loss_pips=1000,
        take_profit_pips=2000,
        trade_mode=1,
        range_n=14,
        direction=True,
        in_high_level=0.5,
        in_low_level=-0.5,
        point_size=0.01,
        verbose=False,
    )

    def __init__(self):
        self.signal = SpearmanRankCorrelationHistogram(
            self.data,
            range_n=self.p.range_n,
            direction=self.p.direction,
            in_high_level=self.p.in_high_level,
            in_low_level=self.p.in_low_level,
        )
        self.last_bar_dt = None
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.stop_price = None
        self.limit_price = None
        self.pending_direction = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        if not self.p.verbose:
            return
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_bar(self):
        current = bt.num2date(self.data.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None
        self.stop_price = None
        self.limit_price = None

    def _place_exit_orders(self):
        if not self.position:
            return
        self._cancel_exit_orders()
        stop_distance = float(self.p.stop_loss_pips) * float(self.p.point_size)
        limit_distance = float(self.p.take_profit_pips) * float(self.p.point_size)
        size = abs(self.position.size)
        if self.position.size > 0:
            if stop_distance > 0:
                self.stop_price = self.position.price - stop_distance
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            if limit_distance > 0:
                self.limit_price = self.position.price + limit_distance
                self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=self.limit_price, oco=self.stop_order)
        else:
            if stop_distance > 0:
                self.stop_price = self.position.price + stop_distance
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            if limit_distance > 0:
                self.limit_price = self.position.price - limit_distance
                self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=self.limit_price, oco=self.stop_order)

    def _signals(self):
        if len(self.signal.color) < 3:
            return False, False, False, False
        col1_value = float(self.signal.color[-1])
        col0_value = float(self.signal.color[-2])
        if not math.isfinite(col1_value) or not math.isfinite(col0_value):
            return False, False, False, False
        col1 = int(col1_value)
        col0 = int(col0_value)
        buy_open = sell_open = buy_close = sell_close = False
        mode = int(self.p.trade_mode)
        if mode == 1:
            if col1 > 2:
                if col0 < 3:
                    buy_open = True
                sell_close = True
            if col1 < 2:
                if col0 > 1:
                    sell_open = True
                buy_close = True
        elif mode == 2:
            if col1 == 4:
                if col0 < 4:
                    buy_open = True
            if col1 > 2:
                sell_close = True
            if col1 == 0:
                if col0 > 0:
                    sell_open = True
            if col1 < 2:
                buy_close = True
        else:
            if col1 == 4:
                if col0 < 4:
                    buy_open = True
                sell_close = True
            if col1 == 0:
                if col0 > 0:
                    sell_open = True
                buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def next(self):
        self.bar_num += 1
        if not self._new_bar():
            return
        if self.entry_order is not None:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        if self.position:
            if self.position.size > 0 and buy_close:
                self._cancel_exit_orders()
                self.close()
                self.log('CLOSE LONG')
                if sell_open:
                    self.pending_direction = 'sell'
                return
            if self.position.size < 0 and sell_close:
                self._cancel_exit_orders()
                self.close()
                self.log('CLOSE SHORT')
                if buy_open:
                    self.pending_direction = 'buy'
                return
            return
        size = max(0.01, float(self.p.fixed_lot))
        direction = self.pending_direction
        if direction is None:
            if buy_open:
                direction = 'buy'
            elif sell_open:
                direction = 'sell'
        if direction == 'buy':
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.pending_direction = None
            self.log('OPEN BUY')
        elif direction == 'sell':
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.pending_direction = None
            self.log('OPEN SELL')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order == self.entry_order:
            if order.status == order.Completed:
                self.entry_order = None
                self._place_exit_orders()
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.entry_order = None
                return
        if order == self.stop_order:
            if order.status == order.Completed:
                self.stop_order = None
                self.limit_order = None
                self.stop_price = None
                self.limit_price = None
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.stop_order = None
                return
        if order == self.limit_order:
            if order.status == order.Completed:
                self.limit_order = None
                self.stop_order = None
                self.stop_price = None
                self.limit_price = None
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._cancel_exit_orders()
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
