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


class FxChaosScalpStrategy(bt.Strategy):
    params = dict(
        lot=0.10,
        stop_loss_pips=50,
        take_profit_pips=50,
        point=0.01,
        h1_zz_start_ago=2,
        d1_zz_start_ago=3,
        fractal_lookback=80,
    )

    def __init__(self):
        self.base_feed = self.datas[0]
        self.h1_feed = self.datas[1]
        self.d1_feed = self.datas[2]
        median_price = (self.h1_feed.high + self.h1_feed.low) / 2.0
        self.ao_fast = bt.indicators.SimpleMovingAverage(median_price, period=5)
        self.ao_slow = bt.indicators.SimpleMovingAverage(median_price, period=34)
        self.ao = self.ao_fast - self.ao_slow
        self.order = None
        self.pending_action = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_base_dt = None
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.base_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        dt = bt.num2date(self.base_feed.datetime[0])
        if self.last_base_dt == dt:
            return
        self.last_base_dt = dt
        if self.order is not None:
            return
        if len(self.h1_feed) < 40 or len(self.d1_feed) < 10:
            return

        if self.position:
            self._check_exit_levels()
            return

        zzf_d1 = self._find_recent_fractal_pivot(self.d1_feed, self.p.d1_zz_start_ago)
        zzf_h1 = self._find_recent_fractal_pivot(self.h1_feed, self.p.h1_zz_start_ago)
        ao_h1 = self._line_value(self.ao, 0)
        high1 = self._line_value(self.h1_feed.high, 1)
        low1 = self._line_value(self.h1_feed.low, 1)
        open_0 = self._line_value(self.base_feed.open, 0)
        close_0 = self._line_value(self.base_feed.close, 0)
        if None in (zzf_d1, zzf_h1, ao_h1, high1, low1, open_0, close_0):
            return

        buy_signal = open_0 < high1 and close_0 > high1 and close_0 < zzf_h1 and ao_h1 < 0 and close_0 > zzf_d1
        sell_signal = open_0 > low1 and close_0 < low1 and close_0 > zzf_h1 and ao_h1 > 0 and close_0 < zzf_d1

        if buy_signal:
            self.pending_action = 'open_long'
            self.order = self.buy(size=float(self.p.lot))
            self.log(f'OPEN LONG close={close_0:.5f} h1_high_1={high1:.5f} zz_h1={zzf_h1:.5f} zz_d1={zzf_d1:.5f} ao={ao_h1:.5f}')
            return
        if sell_signal:
            self.pending_action = 'open_short'
            self.order = self.sell(size=float(self.p.lot))
            self.log(f'OPEN SHORT close={close_0:.5f} h1_low_1={low1:.5f} zz_h1={zzf_h1:.5f} zz_d1={zzf_d1:.5f} ao={ao_h1:.5f}')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.pending_action == 'open_long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self.entry_price = float(order.executed.price)
                self.stop_price = self.entry_price - self._distance(self.p.stop_loss_pips) if self.p.stop_loss_pips else None
                self.take_profit_price = self.entry_price + self._distance(self.p.take_profit_pips) if self.p.take_profit_pips else None
            elif self.pending_action == 'open_short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self.entry_price = float(order.executed.price)
                self.stop_price = self.entry_price + self._distance(self.p.stop_loss_pips) if self.p.stop_loss_pips else None
                self.take_profit_price = self.entry_price - self._distance(self.p.take_profit_pips) if self.p.take_profit_pips else None
            elif self.pending_action == 'close' and not self.position:
                self._clear_trade_levels()
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
            self._clear_trade_levels()

    def _check_exit_levels(self):
        high_0 = self._line_value(self.base_feed.high, 0)
        low_0 = self._line_value(self.base_feed.low, 0)
        if high_0 is None or low_0 is None:
            return False
        if self.position.size > 0:
            if self.stop_price is not None and low_0 <= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and high_0 >= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG take_profit={self.take_profit_price:.5f}')
                return True
            return False
        if self.stop_price is not None and high_0 >= self.stop_price:
            self.pending_action = 'close'
            self.order = self.close()
            self.log(f'CLOSE SHORT stop={self.stop_price:.5f}')
            return True
        if self.take_profit_price is not None and low_0 <= self.take_profit_price:
            self.pending_action = 'close'
            self.order = self.close()
            self.log(f'CLOSE SHORT take_profit={self.take_profit_price:.5f}')
            return True
        return False

    def _find_recent_fractal_pivot(self, data, start_ago):
        max_ago = min(len(data) - 3, int(self.p.fractal_lookback))
        for ago in range(int(start_ago), max_ago + 1):
            pivot = self._fractal_value(data, ago)
            if pivot is not None:
                return pivot
        return None

    @staticmethod
    def _fractal_value(data, ago):
        if ago < 2 or len(data) <= ago + 2:
            return None
        high = float(data.high[-ago])
        low = float(data.low[-ago])
        newer_high_1 = float(data.high[-(ago - 1)])
        newer_high_2 = float(data.high[-(ago - 2)])
        older_high_1 = float(data.high[-(ago + 1)])
        older_high_2 = float(data.high[-(ago + 2)])
        newer_low_1 = float(data.low[-(ago - 1)])
        newer_low_2 = float(data.low[-(ago - 2)])
        older_low_1 = float(data.low[-(ago + 1)])
        older_low_2 = float(data.low[-(ago + 2)])
        is_upper = high > newer_high_1 and high > newer_high_2 and high >= older_high_1 and high >= older_high_2
        if is_upper:
            return high
        is_lower = low < newer_low_1 and low < newer_low_2 and low <= older_low_1 and low <= older_low_2
        if is_lower:
            return low
        return None

    @staticmethod
    def _line_value(line, ago=0):
        value = float(line[-ago] if ago else line[0])
        if not math.isfinite(value):
            return None
        return value

    def _clear_trade_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    def _distance(self, pips):
        return float(pips) * float(self.p.point)
