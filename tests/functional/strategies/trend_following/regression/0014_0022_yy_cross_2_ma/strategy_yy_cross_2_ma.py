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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class YYCross2MAStrategy(bt.Strategy):
    params = dict(
        lot_start=0.01,
        lot_max=0.1,
        ext_profit_ptk=300,
        ext_sl_ptk=0,
        commnt='it-yy.site',
        fast_ma_period=72,
        slow_ma_period=150,
        ma_shift=0,
        price_digits=2,
        volume_step=0.01,
        volume_min=0.01,
        volume_max=1.0,
        point=0.01,
    )

    def __init__(self):
        self.fast_ma = bt.ind.SMA(self.data.close, period=self.p.fast_ma_period)
        self.slow_ma = bt.ind.SMA(self.data.close, period=self.p.slow_ma_period)
        self.entry_order = None
        self.stop_order = None
        self.tp_order = None
        self.stop_price = None
        self.tp_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_volume(self, volume):
        step = self.p.volume_step
        volume = step * int(volume / step)
        volume = max(volume, self.p.volume_min)
        volume = min(volume, min(self.p.lot_max, self.p.volume_max))
        return round(volume, 4)

    def _signal(self):
        ma1_0 = float(self.slow_ma[0])
        ma2_0 = float(self.fast_ma[0])
        ma1_1 = float(self.slow_ma[-1])
        ma2_1 = float(self.fast_ma[-1])

        if ma2_1 > ma1_1 and ma2_0 < ma1_0:
            return 'buy'
        if ma2_1 < ma1_1 and ma2_0 > ma1_0:
            return 'sell'
        return None

    def _cancel_exit_orders(self):
        for order in (self.stop_order, self.tp_order):
            if order is not None and order.alive():
                self.cancel(order)
        self.stop_order = None
        self.tp_order = None

    def _submit_exit_orders(self):
        self._cancel_exit_orders()
        if not self.position:
            return
        if self.position.size > 0:
            if self.stop_price:
                self.stop_order = self.sell(size=abs(self.position.size), exectype=bt.Order.Stop, price=self.stop_price)
            if self.tp_price:
                self.tp_order = self.sell(size=abs(self.position.size), exectype=bt.Order.Limit, price=self.tp_price)
        else:
            if self.stop_price:
                self.stop_order = self.buy(size=abs(self.position.size), exectype=bt.Order.Stop, price=self.stop_price)
            if self.tp_price:
                self.tp_order = self.buy(size=abs(self.position.size), exectype=bt.Order.Limit, price=self.tp_price)

    def _build_levels(self, side, price):
        self.tp_price = None
        self.stop_price = None
        if side == 'buy':
            if self.p.ext_profit_ptk:
                self.tp_price = round(price + self.p.ext_profit_ptk * self.p.point, self.p.price_digits)
            if self.p.ext_sl_ptk:
                self.stop_price = round(price - self.p.ext_sl_ptk * self.p.point, self.p.price_digits)
        else:
            if self.p.ext_profit_ptk:
                self.tp_price = round(price - self.p.ext_profit_ptk * self.p.point, self.p.price_digits)
            if self.p.ext_sl_ptk:
                self.stop_price = round(price + self.p.ext_sl_ptk * self.p.point, self.p.price_digits)

    def _open_signal(self, side):
        lot = self._round_volume(self.p.lot_start)
        price = float(self.data.close[0])
        self._build_levels(side, price)
        if side == 'buy':
            self.entry_order = self.buy(size=lot)
            self.log(f'buy signal price={price:.2f} tp={self.tp_price} sl={self.stop_price}')
        else:
            self.entry_order = self.sell(size=lot)
            self.log(f'sell signal price={price:.2f} tp={self.tp_price} sl={self.stop_price}')

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.slow_ma_period + 2:
            return
        signal = self._signal()
        if signal is None:
            return
        if self.position:
            if signal == 'buy' and self.position.size < 0:
                self.close()
                self._cancel_exit_orders()
            elif signal == 'sell' and self.position.size > 0:
                self.close()
                self._cancel_exit_orders()
            else:
                return
        if self.entry_order is None:
            self._open_signal(signal)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order is self.entry_order:
            if order.status == order.Completed:
                self.entry_order = None
                self._submit_exit_orders()
                if order.isbuy():
                    self.log(f'buy filled price={order.executed.price:.2f}')
                else:
                    self.log(f'sell filled price={order.executed.price:.2f}')
            else:
                self.entry_order = None
            return
        if order in (self.stop_order, self.tp_order):
            if order.status == order.Completed:
                sibling = self.tp_order if order is self.stop_order else self.stop_order
                if sibling is not None and sibling.alive():
                    self.cancel(sibling)
            if order is self.stop_order and order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.stop_order = None
            if order is self.tp_order and order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.tp_order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
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
        self.stop_price = None
        self.tp_price = None
        self.stop_order = None
        self.tp_order = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
