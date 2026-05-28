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


class QuantProbabilityStrategy(bt.Strategy):
    params = dict(
        history_bars=1000,
        lots=0.1,
        risk=2.0,
        stop_loss=0,
        take_profit=0,
        claster_bars=50,
        pips=400,
        magic=777,
        close_sig=0,
        enable_check_bars=True,
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
    )

    def __init__(self):
        self.bullcount = 0
        self.bearcount = 0
        self.bull = 0.0
        self.bear = 0.0
        self.delta_min = 1000.0
        self.delta_max = -10.0
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        lot = min(max(lot, self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 2)

    def lot_size(self):
        lot = self.p.lots
        if self.p.risk > 0:
            lot = self.broker.getcash() * self.p.risk / 100000.0
        return self._normalize_lot(lot)

    def count_trades(self):
        return 1 if self.position else 0

    def _cancel_protective_orders(self):
        if self.stop_order is not None and self.stop_order.alive():
            self.cancel(self.stop_order)
        if self.limit_order is not None and self.limit_order.alive():
            self.cancel(self.limit_order)
        self.stop_order = None
        self.limit_order = None

    def close_all(self, side=None):
        if not self.position:
            return
        if side == 'buy' and self.position.size <= 0:
            return
        if side == 'sell' and self.position.size >= 0:
            return
        self._cancel_protective_orders()
        self.close()

    def check_bars(self):
        self.bullcount = 0
        self.bearcount = 0
        self.delta_min = 1000.0
        self.delta_max = -10.0
        for i in range(self.p.history_bars - self.p.claster_bars, -1, -self.p.claster_bars):
            open_price = float(self.data.open[0] if i == 0 else self.data.open[-i])
            close_price = float(self.data.close[-(i + self.p.claster_bars)])
            delta = abs(close_price - open_price)
            if close_price > open_price and delta >= self.p.pips * self.p.point_size:
                self.bullcount += 1
            if close_price < open_price and delta >= self.p.pips * self.p.point_size:
                self.bearcount += 1
            if delta > self.delta_max:
                self.delta_max = delta
            if delta < self.delta_min:
                self.delta_min = delta
        if self.bullcount > 0 and self.bearcount > 0:
            total = self.bullcount + self.bearcount
            self.bull = round(self.bullcount * 100.0 / total, 2)
            self.bear = round(self.bearcount * 100.0 / total, 2)
        else:
            self.bull = 0.0
            self.bear = 0.0

    def _submit_protective_orders(self, direction, entry_price, size):
        if self.p.stop_loss <= 0 and self.p.take_profit <= 0:
            return
        if direction == 'buy':
            stop_price = round(entry_price - self.p.stop_loss * self.p.point_size, 2) if self.p.stop_loss > 0 else None
            limit_price = round(entry_price + self.p.take_profit * self.p.point_size, 2) if self.p.take_profit > 0 else None
            if stop_price is not None:
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=stop_price)
            if limit_price is not None:
                self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=limit_price, oco=self.stop_order)
        else:
            stop_price = round(entry_price + self.p.stop_loss * self.p.point_size, 2) if self.p.stop_loss > 0 else None
            limit_price = round(entry_price - self.p.take_profit * self.p.point_size, 2) if self.p.take_profit > 0 else None
            if stop_price is not None:
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=stop_price)
            if limit_price is not None:
                self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=limit_price, oco=self.stop_order)

    def next(self):
        self.bar_num += 1
        required = self.p.history_bars + self.p.claster_bars
        if len(self.data) <= required:
            return
        if not self.p.enable_check_bars:
            return
        self.check_bars()
        buy_signal = self.bull > 51.0
        sell_signal = self.bull < 49.0
        if self.p.close_sig > 0:
            if buy_signal:
                self.close_all(side='sell')
            if sell_signal:
                self.close_all(side='buy')
        if self.position or self.entry_order is not None:
            return
        size = self.lot_size()
        if buy_signal and self.count_trades() < 1:
            self.entry_order = self.buy(size=size)
            self.entry_order.addinfo(kind='entry_long')
        elif sell_signal and self.count_trades() < 1:
            self.entry_order = self.sell(size=size)
            self.entry_order.addinfo(kind='entry_short')

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        kind = getattr(order.info, 'kind', None)
        if order.status == order.Completed:
            if kind == 'entry_long':
                self.buy_count += 1
                self.log(f'long entry price={order.executed.price:.2f}')
                self._submit_protective_orders('buy', order.executed.price, order.executed.size)
                self.entry_order = None
            elif kind == 'entry_short':
                self.sell_count += 1
                self.log(f'short entry price={order.executed.price:.2f}')
                self._submit_protective_orders('sell', order.executed.price, abs(order.executed.size))
                self.entry_order = None
            elif order is self.stop_order:
                self.stop_order = None
                self.limit_order = None
            elif order is self.limit_order:
                self.limit_order = None
                self.stop_order = None
        else:
            if order is self.entry_order:
                self.entry_order = None
            if order is self.stop_order:
                self.stop_order = None
            if order is self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._cancel_protective_orders()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
