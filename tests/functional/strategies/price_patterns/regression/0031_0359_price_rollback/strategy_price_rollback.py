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


class PriceRollbackStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=50,
        takeprofit_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        corridor_pips=1,
        lookback_bars=25,
        entry_day_of_week=5,
        entry_hour=0,
        entry_minute_max=3,
        forced_close_hour=22,
        forced_close_minute_threshold=45,
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

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _mql_day_of_week(self, dt):
        return (dt.weekday() + 1) % 7

    def _minimum_bars(self):
        return self.p.lookback_bars + 1

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None

    def _initialize_exit_levels(self, base_price):
        if base_price is None:
            return
        if self.active_side == 'long':
            self.stop_price = None if self.p.stoploss_pips <= 0 else base_price - self.p.stoploss_pips * self.p.point_size
            self.limit_price = None if self.p.takeprofit_pips <= 0 else base_price + self.p.takeprofit_pips * self.p.point_size
        elif self.active_side == 'short':
            self.stop_price = None if self.p.stoploss_pips <= 0 else base_price + self.p.stoploss_pips * self.p.point_size
            self.limit_price = None if self.p.takeprofit_pips <= 0 else base_price - self.p.takeprofit_pips * self.p.point_size

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _submit_entry(self, side, reason, base_price):
        if self.entry_order is not None or self.close_order is not None or self.position:
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.active_side = side
        self.entry_price = None
        self._initialize_exit_levels(base_price)
        if side == 'long':
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN LONG size={size} signal_base={base_price:.5f} reason={reason}')
        else:
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SHORT size={size} signal_base={base_price:.5f} reason={reason}')

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

    def next(self):
        if len(self.data0_feed) < self._minimum_bars():
            return
        dt = bt.num2date(self.data0_feed.datetime[0])
        if dt.hour == self.p.forced_close_hour and dt.minute > self.p.forced_close_minute_threshold:
            self._submit_close('late session forced close')
            return
        if self._check_exit_thresholds():
            return
        self._update_trailing()
        if self.entry_order is not None or self.close_order is not None or self.position:
            return
        if self._mql_day_of_week(dt) != self.p.entry_day_of_week:
            return
        if dt.hour != self.p.entry_hour or dt.minute > self.p.entry_minute_max:
            return
        base_open = float(self.data0_feed.open[0])
        reference_open = float(self.data0_feed.open[-(self.p.lookback_bars - 1)])
        previous_close = float(self.data0_feed.close[-1])
        corridor = self.p.corridor_pips * self.p.point_size
        opcl = reference_open - previous_close
        clop = previous_close - reference_open
        if opcl > corridor:
            self._submit_entry('long', 'rollback corridor buy setup', base_open)
        elif clop > corridor:
            self._submit_entry('short', 'rollback corridor sell setup', base_open)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.entry_price = order.executed.price
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
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
