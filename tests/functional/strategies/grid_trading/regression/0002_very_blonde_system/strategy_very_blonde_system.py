from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume']
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class VeryBlondeSystemStrategy(bt.Strategy):
    params = dict(
        count_bars=10,
        limit_points=240,
        grid_points=35,
        amount=40.0,
        lockdown=0,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        max_lot=0.1,
    )

    def __init__(self):
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.order_refs = set()
        self.pending_grid = []
        self.side = None
        self.locked_down = False

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _base_lot(self):
        lots = round(float(self.broker.getvalue()) / 100.0 / 1000.0, 2)
        return self._lot_check(lots)

    def _lot_check(self, lots):
        if lots <= 0:
            return 0.0
        volume = round(lots, 2)
        step = 0.01
        volume = step * int(volume / step)
        volume = min(volume, float(self.p.max_lot))
        return max(volume, 0.01)

    def _place_grid(self, side, start_price, base_lot):
        unit = self._unit()
        self.pending_grid = []
        for level in range(1, 5):
            volume = self._lot_check((2 ** level) * base_lot)
            if volume == 0:
                continue
            if side == 'buy':
                price = round(start_price - level * float(self.p.grid_points) * unit, int(self.p.price_digits))
                order = self.buy(size=volume, exectype=bt.Order.Limit, price=price)
            else:
                price = round(start_price + level * float(self.p.grid_points) * unit, int(self.p.price_digits))
                order = self.sell(size=volume, exectype=bt.Order.Limit, price=price)
            self.pending_grid.append(order)
            self.order_refs.add(order.ref)

    def _cancel_pending(self):
        for order in list(self.pending_grid):
            if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
                self.cancel(order)
        self.pending_grid = []

    def _open_initial_and_grid(self):
        if self.position or self.pending_grid or len(self) < int(self.p.count_bars) + 1:
            return False
        lookback = int(self.p.count_bars)
        highest = max(float(self.data.high[-i]) for i in range(lookback))
        lowest = min(float(self.data.low[-i]) for i in range(lookback))
        bid = float(self.data.close[0])
        ask = bid
        unit = self._unit()
        base_lot = self._base_lot()
        if base_lot == 0:
            return False
        if highest - bid > float(self.p.limit_points) * unit:
            order = self.buy(size=base_lot)
            self.order_refs.add(order.ref)
            self.side = 'buy'
            self._place_grid('buy', ask, base_lot)
            self.signal_count += 1
            return True
        if bid - lowest > float(self.p.limit_points) * unit:
            order = self.sell(size=base_lot)
            self.order_refs.add(order.ref)
            self.side = 'sell'
            self._place_grid('sell', bid, base_lot)
            self.signal_count += 1
            return True
        return False

    def _apply_lockdown(self):
        if not self.position or self.p.lockdown <= 0:
            return
        unit = self._unit()
        price = float(self.data.close[0])
        if self.position.size > 0 and (price - self.position.price) > float(self.p.lockdown) * unit:
            self.locked_down = True
        if self.position.size < 0 and (self.position.price - price) > float(self.p.lockdown) * unit:
            self.locked_down = True

    def _locked_stop_hit(self):
        if not self.position or not self.locked_down:
            return False
        unit = self._unit()
        if self.position.size > 0:
            return float(self.data.low[0]) <= self.position.price + unit
        return float(self.data.high[0]) >= self.position.price - unit

    def _basket_profit(self):
        return float(self.broker.getvalue() - self.broker.startingcash)

    def next(self):
        self.bar_num += 1
        self._apply_lockdown()
        if self.position and (self._basket_profit() >= float(self.p.amount) or self._locked_stop_hit()):
            self._cancel_pending()
            self.close()
            self.completed_order_count += 1
            self.side = None
            self.locked_down = False
            return
        self._open_initial_and_grid()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if order.isbuy():
                self.buy_count += 1
            elif order.issell():
                self.sell_count += 1
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if order.ref in self.order_refs and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order_refs.discard(order.ref)
            self.pending_grid = [o for o in self.pending_grid if o.ref != order.ref]

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
