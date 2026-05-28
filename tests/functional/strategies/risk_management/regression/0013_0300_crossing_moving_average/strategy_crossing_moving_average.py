from __future__ import absolute_import, division, print_function, unicode_literals

import io

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
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
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


class CrossingMovingAverageStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=50,
        takeprofit_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        minimum_distance_pips=0,
        momentum_filter=0.1,
        ma_first_period=13,
        ma_first_shift=1,
        ma_second_period=34,
        ma_second_shift=3,
        ma_method='ema',
        momentum_period=14,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        ma_cls = bt.indicators.ExponentialMovingAverage if str(self.p.ma_method).lower() == 'ema' else bt.indicators.SimpleMovingAverage
        self.ma_first = ma_cls(self.data0_feed.close, period=self.p.ma_first_period)
        self.ma_second = ma_cls(self.data0_feed.close, period=self.p.ma_second_period)
        self.momentum = bt.indicators.Momentum(self.data0_feed.close, period=self.p.momentum_period)
        self.entry_order = None
        self.close_order = None
        self.pending_side = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _minimum_bars(self):
        return max(self.p.ma_first_period + self.p.ma_first_shift + 3, self.p.ma_second_period + self.p.ma_second_shift + 3, self.p.momentum_period + 3)

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None

    def _initialize_exit_levels(self):
        if not self.position or self.entry_price is None:
            return
        if self.position.size > 0:
            if self.p.stoploss_pips > 0:
                self.stop_price = self.entry_price - self.p.stoploss_pips * self.p.point_size
            else:
                self.stop_price = None
            if self.p.takeprofit_pips > 0:
                self.limit_price = self.entry_price + self.p.takeprofit_pips * self.p.point_size
            else:
                self.limit_price = None
        else:
            if self.p.stoploss_pips > 0:
                self.stop_price = self.entry_price + self.p.stoploss_pips * self.p.point_size
            else:
                self.stop_price = None

    def _submit_entry(self, side, reason):
        if self.entry_order is not None or self.close_order is not None:
            self.pending_side = side
            return
        if self.position.size > 0 and side == 'long':
            return
        if self.position.size < 0 and side == 'short':
            return
        if self.position:
            self.pending_side = side
            self._submit_close(f'reverse to {side}: {reason}')
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.pending_side = None
        if side == 'long':
            self.entry_order = self.buy(size=size)
            self.log(f'OPEN LONG size={size} reason={reason}')
        else:
            self.entry_order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size} reason={reason}')

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _check_exit_thresholds(self):
        if not self.position or self.entry_price is None or self.close_order is not None:
            return False
        bar_high = float(self.data0_feed.high[0])
        bar_low = float(self.data0_feed.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and bar_low <= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_high >= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        else:
            if self.stop_price is not None and bar_high >= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_low <= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        return False

    def _update_trailing(self):
        if not self.position or self.p.trailing_stop_pips <= 0 or self.entry_price is None:
            return
        trail_distance = self.p.trailing_stop_pips * self.p.point_size
        trail_gate = (self.p.trailing_stop_pips + self.p.trailing_step_pips) * self.p.point_size
        close_price = float(self.data0_feed.close[0])
        if self.position.size > 0:
            if close_price - self.entry_price > trail_gate:
                candidate = close_price - trail_distance
                if self.stop_price is None or candidate > self.stop_price + 1e-12:
                    self.stop_price = candidate
                    self.log(f'UPDATE LONG TRAIL stop={self.stop_price:.5f}')
        else:
            if self.entry_price - close_price > trail_gate:
                candidate = close_price + trail_distance
                if self.stop_price is None or candidate < self.stop_price - 1e-12:
                    self.stop_price = candidate
                    self.log(f'UPDATE SHORT TRAIL stop={self.stop_price:.5f}')

    def next(self):
        if len(self.data0_feed) < self._minimum_bars():
            return
        if self._check_exit_thresholds():
            return
        self._update_trailing()
        if self.entry_order is not None or self.close_order is not None:
            return
        first_now = float(self.ma_first[-1 - self.p.ma_first_shift])
        first_prev = float(self.ma_first[-2 - self.p.ma_first_shift])
        second_now = float(self.ma_second[-1 - self.p.ma_second_shift])
        second_prev = float(self.ma_second[-2 - self.p.ma_second_shift])
        cur_mom = float(self.momentum[-1])
        prev_mom = float(self.momentum[-2])
        min_dist = self.p.minimum_distance_pips * self.p.point_size
        buy_signal = first_now > second_now + min_dist and first_prev < second_prev - min_dist and cur_mom > self.p.momentum_filter and cur_mom > prev_mom
        sell_signal = first_now < second_now - min_dist and first_prev > second_prev + min_dist and cur_mom < -self.p.momentum_filter and cur_mom < prev_mom
        if buy_signal:
            self._submit_entry('long', 'ma bullish cross with momentum filter')
        elif sell_signal:
            self._submit_entry('short', 'ma bearish cross with momentum filter')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_price = order.executed.price
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
                self._initialize_exit_levels()
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self._reset_exit_levels()
                if self.pending_side is not None:
                    next_side = self.pending_side
                    self.pending_side = None
                    self._submit_entry(next_side, 'post-close reversal')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.entry_price = None
            self._reset_exit_levels()
