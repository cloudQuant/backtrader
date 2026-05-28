from __future__ import absolute_import, division, print_function, unicode_literals

import io
from collections import OrderedDict

import backtrader as bt
import backtrader.feeds as btfeeds
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class JollyRogerStrategy(bt.Strategy):
    params = dict(
        tp=150,
        sl=50,
        rsi_period=14,
        rsi_level=30,
        point=0.01,
        stop_level_points=0.0,
        spread_points=0.0,
        repricing_distance_points=20.0,
        order_split=3,
        min_lot=0.1,
        max_lot=15.0,
        margin_divisor=2000.0,
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_entry_orders = OrderedDict()
        self.pending_entry_side = None
        self.pending_entry_price = None
        self.pending_requeue = None
        self.exit_order = None
        self.exit_leg_ids = []
        self.legs = []
        self.next_leg_id = 1
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _point(self):
        return float(self.p.point)

    def _clamp_total_volume(self):
        total = float(self.broker.getcash()) / float(self.p.margin_divisor)
        total = min(float(self.p.max_lot), max(float(self.p.min_lot), total))
        return round(total, 2)

    def _entry_size(self):
        return round(self._clamp_total_volume() / float(self.p.order_split), 2)

    def _entry_price_for_side(self, side, base_price=None, use_repricing_gap=False):
        if base_price is None:
            base_price = float(self.data.close[0])
        gap_points = float(self.p.repricing_distance_points) if use_repricing_gap else float(self.p.stop_level_points)
        if side == 'buy':
            return base_price + gap_points * self._point()
        return base_price - gap_points * self._point()

    def _leg_stop(self, side, entry_price, market_price=None):
        point = self._point()
        spread = float(self.p.spread_points) * point
        stop_dist = float(self.p.sl) * point
        stop_level = float(self.p.stop_level_points) * point
        if market_price is None:
            market_price = float(self.data.close[0])
        if side == 'buy':
            candidate = max(entry_price + spread, market_price - stop_dist)
            if market_price - stop_level - spread > entry_price:
                return candidate
            return entry_price - stop_dist
        candidate = min(entry_price - spread, market_price + stop_dist)
        if entry_price - stop_level - spread > market_price:
            return candidate
        return entry_price + stop_dist

    def _leg_take(self, side, entry_price):
        take_dist = float(self.p.tp) * self._point()
        if side == 'buy':
            return entry_price + take_dist
        return entry_price - take_dist

    def _submit_entry_batch(self, side, count=None, entry_price=None):
        if count is None:
            count = int(self.p.order_split)
        if count <= 0:
            return
        size = self._entry_size()
        if size <= 0:
            return
        if entry_price is None:
            entry_price = self._entry_price_for_side(side)
        self.pending_entry_side = side
        self.pending_entry_price = entry_price
        for _ in range(count):
            if side == 'buy':
                order = self.buy(size=size, exectype=bt.Order.Stop, price=entry_price)
            else:
                order = self.sell(size=size, exectype=bt.Order.Stop, price=entry_price)
            self.pending_entry_orders[order.ref] = {'side': side, 'planned_price': entry_price, 'size': size}
        self.log(f'PLACE {count} {side.upper()}_STOP orders price={entry_price:.2f} size={size:.2f}')

    def _cancel_pending_entries(self, requeue=None):
        if requeue is not None:
            self.pending_requeue = requeue
        for order in list(self.pending_entry_orders.values()):
            pass
        for order_ref in list(self.pending_entry_orders.keys()):
            for o in self.broker.orders:
                if o.ref == order_ref:
                    self.cancel(o)
                    break

    def _refresh_pending_entry_state(self):
        if self.pending_entry_orders:
            first_meta = next(iter(self.pending_entry_orders.values()))
            self.pending_entry_side = first_meta['side']
            self.pending_entry_price = first_meta['planned_price']
        else:
            self.pending_entry_side = None
            self.pending_entry_price = None

    def _maybe_reprice_pending_entries(self):
        if not self.pending_entry_orders or self.pending_requeue is not None:
            return
        close_price = float(self.data.close[0])
        point = self._point()
        threshold = float(self.p.repricing_distance_points) * point
        if self.pending_entry_side == 'buy':
            if self.pending_entry_price - close_price > threshold:
                remaining = len(self.pending_entry_orders)
                new_price = self._entry_price_for_side('buy', base_price=close_price, use_repricing_gap=True)
                self.log(f'REPRICE BUY_STOP orders -> {new_price:.2f}')
                self._cancel_pending_entries(requeue={'side': 'buy', 'count': remaining, 'price': new_price})
        elif self.pending_entry_side == 'sell':
            if close_price - self.pending_entry_price > threshold:
                remaining = len(self.pending_entry_orders)
                new_price = self._entry_price_for_side('sell', base_price=close_price, use_repricing_gap=True)
                self.log(f'REPRICE SELL_STOP orders -> {new_price:.2f}')
                self._cancel_pending_entries(requeue={'side': 'sell', 'count': remaining, 'price': new_price})

    def _update_trailing_stops(self):
        if not self.legs:
            return
        market_price = float(self.data.close[0])
        for leg in self.legs:
            leg['sl'] = self._leg_stop(leg['side'], leg['entry_price'], market_price=market_price)

    def _check_leg_exits(self):
        if self.exit_order is not None or not self.legs:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        triggered_ids = []
        close_size = 0.0
        reasons = []
        for leg in self.legs:
            if leg['side'] == 'buy':
                hit_sl = leg['sl'] is not None and low <= leg['sl']
                hit_tp = leg['tp'] is not None and high >= leg['tp']
                if hit_sl or hit_tp:
                    triggered_ids.append(leg['id'])
                    close_size += leg['size']
                    reasons.append('sl' if hit_sl else 'tp')
            else:
                hit_sl = leg['sl'] is not None and high >= leg['sl']
                hit_tp = leg['tp'] is not None and low <= leg['tp']
                if hit_sl or hit_tp:
                    triggered_ids.append(leg['id'])
                    close_size += leg['size']
                    reasons.append('sl' if hit_sl else 'tp')
        if not triggered_ids or close_size <= 0:
            return False
        close_size = min(close_size, abs(float(self.position.size)))
        self.exit_leg_ids = triggered_ids
        self.exit_order = self.close(size=close_size)
        self.log(f'CLOSE partial size={close_size:.2f} reason={"/".join(reasons)}')
        return True

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(self.p.rsi_period + 2, 20):
            return
        if self.exit_order is not None:
            return

        self._update_trailing_stops()
        if self._check_leg_exits():
            return
        self._maybe_reprice_pending_entries()

        if self.position or self.pending_entry_orders or self.pending_requeue is not None:
            return

        rsi_prev = float(self.rsi[-1])
        if rsi_prev < float(self.p.rsi_level):
            self.signal_count += 1
            self._submit_entry_batch('buy')
            return
        if rsi_prev > 100.0 - float(self.p.rsi_level):
            self.signal_count += 1
            self._submit_entry_batch('sell')
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.ref in self.pending_entry_orders:
            meta = self.pending_entry_orders.pop(order.ref)
            if order.status == order.Completed:
                side = meta['side']
                leg = {
                    'id': self.next_leg_id,
                    'side': side,
                    'size': abs(float(order.executed.size)),
                    'entry_price': float(order.executed.price),
                    'sl': self._leg_stop(side, float(order.executed.price)),
                    'tp': self._leg_take(side, float(order.executed.price)),
                }
                self.next_leg_id += 1
                self.legs.append(leg)
                if side == 'buy':
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.log(f'ENTRY FILLED side={side} price={order.executed.price:.2f} size={abs(order.executed.size):.2f}')
            elif order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.log(f'PENDING ENTRY {order.getstatusname()} ref={order.ref}')

            self._refresh_pending_entry_state()
            if not self.pending_entry_orders and self.pending_requeue is not None:
                requeue = self.pending_requeue
                self.pending_requeue = None
                self._submit_entry_batch(requeue['side'], count=requeue['count'], entry_price=requeue['price'])
            return

        if self.exit_order is not None and order.ref == self.exit_order.ref:
            if order.status == order.Completed:
                leg_ids = set(self.exit_leg_ids)
                self.legs = [leg for leg in self.legs if leg['id'] not in leg_ids]
                self.log(f'EXIT FILLED size={abs(order.executed.size):.2f} price={order.executed.price:.2f}')
            elif order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.log(f'EXIT {order.getstatusname()} ref={order.ref}')
            self.exit_order = None
            self.exit_leg_ids = []
            return

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
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
