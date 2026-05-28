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


class JsMaDayStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        ma_period=3,
        close_hour=23,
        reverse_signals=False,
        stoploss_pips=50,
        takeprofit_pips=300,
        trailing_stop_pips=15,
        trailing_step_pips=5,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.entry_order = None
        self.close_order = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None
        self.buy_count = 0
        self.sell_count = 0
        self.completed_days = []
        self.current_day = None
        self.current_day_open = None
        self.current_day_high = None
        self.current_day_low = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None

    def _initialize_exit_levels(self):
        if self.entry_price is None or self.active_side is None:
            return
        if self.active_side == 'long':
            self.stop_price = None if self.p.stoploss_pips <= 0 else self.entry_price - self.p.stoploss_pips * self.p.point_size
            self.limit_price = None if self.p.takeprofit_pips <= 0 else self.entry_price + self.p.takeprofit_pips * self.p.point_size
        else:
            self.stop_price = None if self.p.stoploss_pips <= 0 else self.entry_price + self.p.stoploss_pips * self.p.point_size
            self.limit_price = None if self.p.takeprofit_pips <= 0 else self.entry_price - self.p.takeprofit_pips * self.p.point_size

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _submit_entry(self, side, reason):
        if self.entry_order is not None or self.close_order is not None or self.position:
            return
        size = max(0.01, float(self.p.fixed_lot))
        if side == 'long':
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN LONG size={size} reason={reason}')
        else:
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SHORT size={size} reason={reason}')
        self.active_side = side

    def _check_exit_thresholds(self):
        if not self.position or self.close_order is not None:
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

    def _roll_day_state(self):
        dt = bt.num2date(self.data0_feed.datetime[0])
        day_key = dt.date()
        bar_open = float(self.data0_feed.open[0])
        bar_high = float(self.data0_feed.high[0])
        bar_low = float(self.data0_feed.low[0])
        if self.current_day != day_key:
            if self.current_day is not None:
                self.completed_days.append({
                    'open': self.current_day_open,
                    'median': (self.current_day_high + self.current_day_low) / 2.0,
                })
                self.completed_days = self.completed_days[-32:]
            self.current_day = day_key
            self.current_day_open = bar_open
            self.current_day_high = bar_high
            self.current_day_low = bar_low
        else:
            self.current_day_high = max(self.current_day_high, bar_high)
            self.current_day_low = min(self.current_day_low, bar_low)
        return dt

    def _daily_ma_values(self):
        current_median = (self.current_day_high + self.current_day_low) / 2.0
        medians = [current_median] + [item['median'] for item in reversed(self.completed_days)]
        opens = [self.current_day_open] + [item['open'] for item in reversed(self.completed_days)]
        need = self.p.ma_period + 2
        if len(medians) < need or len(opens) < 2:
            return None
        ma0 = sum(medians[0:self.p.ma_period]) / self.p.ma_period
        ma1 = sum(medians[1:1 + self.p.ma_period]) / self.p.ma_period
        ma2 = sum(medians[2:2 + self.p.ma_period]) / self.p.ma_period
        open0 = opens[0]
        open1 = opens[1]
        return ma0, ma1, ma2, open0, open1

    def next(self):
        dt = self._roll_day_state()
        if self._check_exit_thresholds():
            return
        self._update_trailing()
        if self.p.close_hour >= 0 and dt.hour >= self.p.close_hour:
            self._submit_close('scheduled close hour')
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        if self.position:
            return
        values = self._daily_ma_values()
        if values is None:
            return
        ma0, ma1, ma2, open0, open1 = values
        long_signal = ma0 < ma1 and ma0 > open0 and ma1 < ma2 and ma1 > open1
        short_signal = ma0 > ma1 and ma0 < open0 and ma1 > ma2 and ma1 < open1
        if self.p.reverse_signals:
            long_signal, short_signal = short_signal, long_signal
        if long_signal:
            self._submit_entry('long', 'daily MA/day-open bullish pattern')
        elif short_signal:
            self._submit_entry('short', 'daily MA/day-open bearish pattern')

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
