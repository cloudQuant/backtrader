from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


FIBO_MAP = {
    '0': 0.0,
    '23_6': 23.6,
    '38_2': 38.2,
    '50_0': 50.0,
    '61_8': 61.8,
    '100_0': 100.0,
    '161_8': 161.8,
    '261_8': 261.8,
    '423_6': 423.6,
}


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


class ZigZagEAStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        depth=12,
        deviation=5,
        backstep=3,
        start_hour=0,
        start_minute=1,
        stop_hour=23,
        stop_minute=59,
        n_pips=5,
        min_corridor_pips=20,
        max_corridor_pips=100,
        fibo_stop='61_8',
        fibo_takeprofit='161_8',
        trailing_stop_pips=5,
        trailing_step_pips=5,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.buy_stop_order = None
        self.sell_stop_order = None
        self.close_order = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None
        self.pivots = []
        self.last_pivot_dt = None
        self.last_pending_signature = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _minimum_bars(self):
        return self.p.depth * 3 + 20

    def _fibo_value(self, key):
        return FIBO_MAP[str(key)]

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None

    def _cancel_pending_orders(self):
        if self.buy_stop_order is not None:
            self.cancel(self.buy_stop_order)
            self.buy_stop_order = None
        if self.sell_stop_order is not None:
            self.cancel(self.sell_stop_order)
            self.sell_stop_order = None
        self.last_pending_signature = None

    def _initialize_exit_levels(self, corridor_size):
        if not self.position or self.entry_price is None:
            return
        stop_distance = corridor_size * self._fibo_value(self.p.fibo_stop) / 100.0
        tp_distance = corridor_size * (self._fibo_value(self.p.fibo_takeprofit) - 100.0) / 100.0
        if self.position.size > 0:
            self.stop_price = self.entry_price - stop_distance if stop_distance > 0 else None
            self.limit_price = self.entry_price + tp_distance if tp_distance > 0 else None
        else:
            self.stop_price = self.entry_price + stop_distance if stop_distance > 0 else None
            self.limit_price = self.entry_price - tp_distance if tp_distance > 0 else None

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
        if not self.position or self.entry_price is None or self.p.trailing_stop_pips <= 0:
            return
        close_price = float(self.data0_feed.close[0])
        trail_distance = self.p.trailing_stop_pips * self.p.point_size
        trail_gate = (self.p.trailing_stop_pips + self.p.trailing_step_pips) * self.p.point_size
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

    def _in_operation_window(self):
        dt = bt.num2date(self.data0_feed.datetime[0])
        current = dt.hour * 60 + dt.minute
        start = self.p.start_hour * 60 + self.p.start_minute
        stop = self.p.stop_hour * 60 + self.p.stop_minute
        if start <= stop:
            return start <= current <= stop
        return current >= start or current <= stop

    def _append_pivot(self, pivot_type, price, dt):
        if self.last_pivot_dt == dt:
            return
        deviation_value = self.p.deviation * self.p.point_size
        if self.pivots:
            last = self.pivots[-1]
            if last['type'] == pivot_type:
                if pivot_type == 'high' and price >= last['price']:
                    self.pivots[-1] = {'type': pivot_type, 'price': price, 'dt': dt}
                    self.last_pivot_dt = dt
                elif pivot_type == 'low' and price <= last['price']:
                    self.pivots[-1] = {'type': pivot_type, 'price': price, 'dt': dt}
                    self.last_pivot_dt = dt
                return
            if abs(price - last['price']) < deviation_value:
                return
        self.pivots.append({'type': pivot_type, 'price': price, 'dt': dt})
        self.pivots = self.pivots[-20:]
        self.last_pivot_dt = dt

    def _update_pivots(self):
        if len(self.data0_feed) < self.p.depth * 2 + 5:
            return
        idx = -self.p.depth
        window_highs = [float(self.data0_feed.high[i]) for i in range(-2 * self.p.depth, 1)]
        window_lows = [float(self.data0_feed.low[i]) for i in range(-2 * self.p.depth, 1)]
        candidate_high = float(self.data0_feed.high[idx])
        candidate_low = float(self.data0_feed.low[idx])
        pivot_dt = bt.num2date(self.data0_feed.datetime[idx])
        center = self.p.depth
        if window_highs[center] == max(window_highs):
            self._append_pivot('high', candidate_high, pivot_dt)
        if window_lows[center] == min(window_lows):
            self._append_pivot('low', candidate_low, pivot_dt)

    def _corridor_setup(self):
        if len(self.pivots) < 3:
            return None
        room_0 = self.pivots[-1]['price']
        room_1 = self.pivots[-2]['price']
        room_2 = self.pivots[-3]['price']
        high = max(room_1, room_2)
        low = min(room_1, room_2)
        size_corridor = high - low
        min_corridor = self.p.min_corridor_pips * self.p.point_size
        max_corridor = self.p.max_corridor_pips * self.p.point_size
        if not (size_corridor > min_corridor and size_corridor < max_corridor):
            return None
        stop_level = 0.0
        if not (high > room_0 + stop_level and low < room_0 - stop_level):
            return None
        buy_level = round(high / self.p.point_size + self.p.n_pips) * self.p.point_size
        sell_level = round(low / self.p.point_size - self.p.n_pips) * self.p.point_size
        return {
            'room_0': room_0,
            'high': high,
            'low': low,
            'size_corridor': size_corridor,
            'buy_level': buy_level,
            'sell_level': sell_level,
        }

    def _sync_pending_orders(self, setup):
        if self.position or self.close_order is not None:
            self._cancel_pending_orders()
            return
        if not self._in_operation_window() or setup is None:
            self._cancel_pending_orders()
            return
        signature = (round(setup['buy_level'], 5), round(setup['sell_level'], 5), round(setup['size_corridor'], 5))
        if signature == self.last_pending_signature and self.buy_stop_order is not None and self.sell_stop_order is not None:
            return
        self._cancel_pending_orders()
        size = max(0.01, float(self.p.fixed_lot))
        self.buy_stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=setup['buy_level'])
        self.sell_stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=setup['sell_level'])
        self.last_pending_signature = signature
        self.log(f'PLACE OCO BUY_STOP={setup["buy_level"]:.5f} SELL_STOP={setup["sell_level"]:.5f} corridor={setup["size_corridor"]:.5f}')

    def next(self):
        if len(self.data0_feed) < self._minimum_bars():
            return
        self._update_pivots()
        if self._check_exit_thresholds():
            return
        self._update_trailing()
        setup = self._corridor_setup()
        self._sync_pending_orders(setup)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            setup = self._corridor_setup()
            corridor_size = setup['size_corridor'] if setup is not None else None
            if order == self.buy_stop_order:
                self.buy_stop_order = None
                self.active_side = 'long'
                self.entry_price = order.executed.price
                self._cancel_pending_orders()
                self.log(f'ENTRY FILLED side=long price={order.executed.price:.5f} size={order.executed.size}')
                if corridor_size is not None:
                    self._initialize_exit_levels(corridor_size)
            elif order == self.sell_stop_order:
                self.sell_stop_order = None
                self.active_side = 'short'
                self.entry_price = order.executed.price
                self._cancel_pending_orders()
                self.log(f'ENTRY FILLED side=short price={order.executed.price:.5f} size={order.executed.size}')
                if corridor_size is not None:
                    self._initialize_exit_levels(corridor_size)
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self._reset_exit_levels()
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.buy_stop_order:
                self.buy_stop_order = None
            elif order == self.sell_stop_order:
                self.sell_stop_order = None
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
