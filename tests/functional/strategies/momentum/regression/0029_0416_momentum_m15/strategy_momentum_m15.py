from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
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
    keep_cols = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']
    if 'spread' in df.columns:
        keep_cols.append('spread')
    df = df[keep_cols]
    if 'spread' not in df.columns:
        df['spread'] = 0
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class MomentumM15Strategy(bt.Strategy):
    params = dict(
        lot=0.10,
        trailing_stop_pips=0.0,
        ma_period=26,
        ma_shift=8,
        mo_min=100.0,
        mo_shift=-0.2,
        momentum_period=23,
        mo_open_time=6,
        mo_close_time=10,
        point=0.01,
        gap_level=30,
        gap_timeout=100,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.ma = bt.indicators.SmoothedMovingAverage(self.data0.low, period=self.p.ma_period)
        self.order = None
        self.pending_action = None
        self.trailing_level = None
        self.gap_timer = 0
        self.last_dt = None
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        dt = bt.num2date(self.data0.datetime[0])
        if self.last_dt == dt:
            return
        self.last_dt = dt
        if len(self.data0) < max(100, self.p.ma_period + self.p.ma_shift + self.p.momentum_period + self.p.mo_close_time + 2):
            return
        if self.order is not None:
            return

        if self._is_gap_active():
            return

        if not self.position:
            self._check_for_open()
        else:
            self._check_for_close()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.pending_action == 'open_long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self.trailing_level = None
            elif self.pending_action == 'open_short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self.trailing_level = None
            elif self.pending_action == 'close' and not self.position:
                self.trailing_level = None
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            self.pending_action = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f}')
        if not self.position:
            self.trailing_level = None

    def _is_gap_active(self):
        gap = int(round((float(self.data0.open[0]) - float(self.data0.close[-1])) / float(self.p.point)))
        if gap > int(self.p.gap_level):
            self.gap_timer = int(self.p.gap_timeout)
        if self.gap_timer > 0:
            self.gap_timer -= 1
            if self.gap_timer > 0:
                return True
        return False

    def _check_for_open(self):
        ma_value = self._ma_value()
        momentum_value = self._momentum_value(0)
        if ma_value is None or momentum_value is None:
            return
        prev_close = float(self.data0.close[-1])
        current_open = float(self.data0.open[0])
        if momentum_value < (float(self.p.mo_min) + float(self.p.mo_shift)):
            if prev_close < ma_value and current_open < ma_value:
                if self._check_momentum_down(int(self.p.mo_open_time)):
                    self.pending_action = 'open_long'
                    self.order = self.buy(size=float(self.p.lot))
                    self.log(f'OPEN LONG open={current_open:.5f} prev_close={prev_close:.5f} ma={ma_value:.5f} momentum={momentum_value:.5f}')
                    return
        if momentum_value > (float(self.p.mo_min) - float(self.p.mo_shift)):
            if prev_close > ma_value and current_open > ma_value:
                if self._check_momentum_up(int(self.p.mo_open_time)):
                    self.pending_action = 'open_short'
                    self.order = self.sell(size=float(self.p.lot))
                    self.log(f'OPEN SHORT open={current_open:.5f} prev_close={prev_close:.5f} ma={ma_value:.5f} momentum={momentum_value:.5f}')

    def _check_for_close(self):
        ma_value = self._ma_value()
        if ma_value is None:
            return
        prev_close = float(self.data0.close[-1])
        if self.position.size > 0:
            if self._check_momentum_down(int(self.p.mo_close_time)) or prev_close < ma_value:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG prev_close={prev_close:.5f} ma={ma_value:.5f}')
                return
            self._update_long_trailing()
            return
        if self._check_momentum_up(int(self.p.mo_close_time)) or prev_close > ma_value:
            self.pending_action = 'close'
            self.order = self.close()
            self.log(f'CLOSE SHORT prev_close={prev_close:.5f} ma={ma_value:.5f}')
            return
        self._update_short_trailing()

    def _update_long_trailing(self):
        if float(self.p.trailing_stop_pips) <= 0:
            return
        new_level = float(self.data0.open[0]) - self._distance(self.p.trailing_stop_pips)
        if self.trailing_level is None or new_level > self.trailing_level:
            self.trailing_level = new_level
        if float(self.data0.low[0]) <= self.trailing_level:
            self.pending_action = 'close'
            self.order = self.close()
            self.log(f'CLOSE LONG trailing={self.trailing_level:.5f}')

    def _update_short_trailing(self):
        if float(self.p.trailing_stop_pips) <= 0:
            return
        new_level = float(self.data0.open[0]) + self._distance(self.p.trailing_stop_pips)
        if self.trailing_level is None or new_level < self.trailing_level:
            self.trailing_level = new_level
        if float(self.data0.high[0]) >= self.trailing_level:
            self.pending_action = 'close'
            self.order = self.close()
            self.log(f'CLOSE SHORT trailing={self.trailing_level:.5f}')

    def _ma_value(self):
        if len(self.ma) <= int(self.p.ma_shift):
            return None
        value = float(self.ma[-int(self.p.ma_shift)])
        if not math.isfinite(value):
            return None
        return value

    def _momentum_value(self, ago):
        lookback = ago + int(self.p.momentum_period)
        if len(self.data0) <= lookback:
            return None
        base = float(self.data0.open[-lookback])
        if base == 0.0:
            return None
        current = float(self.data0.open[-ago] if ago else self.data0.open[0])
        return 100.0 * current / base

    def _check_momentum_down(self, count):
        values = []
        for ago in range(count - 1, -1, -1):
            value = self._momentum_value(ago)
            if value is None:
                return False
            values.append(value)
        return all(values[i] >= values[i + 1] for i in range(len(values) - 1))

    def _check_momentum_up(self, count):
        values = []
        for ago in range(count - 1, -1, -1):
            value = self._momentum_value(ago)
            if value is None:
                return False
            values.append(value)
        return all(values[i] <= values[i + 1] for i in range(len(values) - 1))

    def _distance(self, pips):
        return float(pips) * float(self.p.point)
