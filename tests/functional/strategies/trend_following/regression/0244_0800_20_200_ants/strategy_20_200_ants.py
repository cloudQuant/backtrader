from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TwentyTwoHundredAntsStrategy(bt.Strategy):
    params = dict(
        t1=6,
        t2=2,
        delta_l=6,
        delta_s=21,
        take_profit_l=390,
        stop_loss_l=1470,
        take_profit_s=320,
        stop_loss_s=2670,
        lot=0.1,
        auto_lot=True,
        big_lot_size=6.0,
        one_mult=True,
        trade_hour=14,
        max_open_hours=504,
        point=0.01,
        price_digits=2,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.entry_order_ref = None
        self.stop_order = None
        self.stop_order_ref = None
        self.limit_order = None
        self.limit_order_ref = None
        self.close_order = None
        self.close_order_ref = None
        self.position_open_dt = None
        self.last_trade_was_loss = False
        self.prev_lot_reference = None
        self.last_entry_size = 0.0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _has_pending_orders(self):
        return any(order is not None for order in (self.entry_order, self.stop_order, self.limit_order, self.close_order))

    def _normalize_lot(self, lot):
        lot = max(self.p.lot_min, min(self.p.lot_max, lot))
        steps = round((lot - self.p.lot_min) / self.p.lot_step)
        normalized = self.p.lot_min + steps * self.p.lot_step
        return round(max(self.p.lot_min, min(self.p.lot_max, normalized)), 2)

    def _auto_lot_value(self):
        balance = float(self.broker.getcash())
        if balance < 300:
            return self._normalize_lot(self.p.lot)
        return self._normalize_lot(balance / 27400.0)

    def _compute_entry_lot(self):
        base_lot = self._auto_lot_value() if self.p.auto_lot else self._normalize_lot(self.p.lot)
        lot = base_lot
        if self.last_trade_was_loss:
            if self.p.auto_lot and self.prev_lot_reference is not None:
                lot = self.prev_lot_reference
            lot = self._normalize_lot(lot * self.p.big_lot_size)
        if self.p.one_mult:
            self.prev_lot_reference = base_lot
        else:
            self.prev_lot_reference = lot
        return lot

    def _entry_prices(self, is_long):
        price = float(self.data.close[0])
        if is_long:
            stop_price = price - self.p.stop_loss_l * self.p.point
            limit_price = price + self.p.take_profit_l * self.p.point
        else:
            stop_price = price + self.p.stop_loss_s * self.p.point
            limit_price = price - self.p.take_profit_s * self.p.point
        return round(stop_price, self.p.price_digits), round(limit_price, self.p.price_digits)

    def _cancel_exit_orders(self):
        for order in (self.stop_order, self.limit_order):
            if order is not None:
                self.cancel(order)
        self.stop_order = None
        self.stop_order_ref = None
        self.limit_order = None
        self.limit_order_ref = None

    def _signal_open_buy(self):
        op1 = float(self.data.open[-self.p.t1])
        op2 = float(self.data.open[-self.p.t2])
        return (op2 - op1) > self.p.point * self.p.delta_l

    def _signal_open_sell(self):
        op1 = float(self.data.open[-self.p.t1])
        op2 = float(self.data.open[-self.p.t2])
        return (op1 - op2) > self.p.point * self.p.delta_s

    def next(self):
        self.bar_num += 1
        if len(self.data) <= max(self.p.t1, self.p.t2) + 2:
            return

        dt = bt.num2date(self.data.datetime[0])

        if self.position and self.p.max_open_hours > 0 and self.position_open_dt is not None:
            elapsed = dt - self.position_open_dt
            if elapsed >= datetime.timedelta(hours=self.p.max_open_hours):
                self.log(f'close by max_open_hours elapsed_hours={elapsed.total_seconds() / 3600.0:.2f}')
                self._cancel_exit_orders()
                if self.close_order is None:
                    self.close_order = self.close()
                    self.close_order_ref = self.close_order.ref if self.close_order is not None else None
                return

        if self.position or self._has_pending_orders():
            return

        if dt.hour != self.p.trade_hour:
            return

        open_buy = self._signal_open_buy()
        open_sell = self._signal_open_sell()
        if open_buy == open_sell:
            return

        size = self._compute_entry_lot()
        self.last_entry_size = size

        if open_buy:
            stop_price, limit_price = self._entry_prices(is_long=True)
            self.log(f'buy size={size:.2f} stop={stop_price:.2f} limit={limit_price:.2f}')
            orders = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=stop_price, limitprice=limit_price)
        else:
            stop_price, limit_price = self._entry_prices(is_long=False)
            self.log(f'sell size={size:.2f} stop={stop_price:.2f} limit={limit_price:.2f}')
            orders = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=stop_price, limitprice=limit_price)

        self.entry_order, self.stop_order, self.limit_order = orders
        self.entry_order_ref = self.entry_order.ref if self.entry_order is not None else None
        self.stop_order_ref = self.stop_order.ref if self.stop_order is not None else None
        self.limit_order_ref = self.limit_order.ref if self.limit_order is not None else None

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if self.entry_order_ref is not None and order.ref == self.entry_order_ref:
            if order.status == bt.Order.Completed:
                self.position_open_dt = bt.num2date(order.executed.dt)
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.log(f'entry filled price={order.executed.price:.2f} size={order.executed.size:.2f}')
            elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'entry failed status={order.getstatusname()}')
                self.stop_order = None
                self.stop_order_ref = None
                self.limit_order = None
                self.limit_order_ref = None
            if order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
                self.entry_order = None
                self.entry_order_ref = None
            return

        if self.stop_order_ref is not None and order.ref == self.stop_order_ref:
            if order.status == bt.Order.Completed:
                self.log(f'stop filled price={order.executed.price:.2f}')
            if order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
                self.stop_order = None
                self.stop_order_ref = None
            return

        if self.limit_order_ref is not None and order.ref == self.limit_order_ref:
            if order.status == bt.Order.Completed:
                self.log(f'take profit filled price={order.executed.price:.2f}')
            if order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
                self.limit_order = None
                self.limit_order_ref = None
            return

        if self.close_order_ref is not None and order.ref == self.close_order_ref:
            if order.status == bt.Order.Completed:
                self.log(f'manual close filled price={order.executed.price:.2f}')
            if order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
                self.close_order = None
                self.close_order_ref = None
            return

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.last_trade_was_loss = trade.pnlcomm < 0
        if self.last_trade_was_loss:
            self.loss_count += 1
        else:
            self.win_count += 1
        self.position_open_dt = None
        self.close_order = None
        self.close_order_ref = None
        self.entry_order = None
        self.entry_order_ref = None
        self.stop_order = None
        self.stop_order_ref = None
        self.limit_order = None
        self.limit_order_ref = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
