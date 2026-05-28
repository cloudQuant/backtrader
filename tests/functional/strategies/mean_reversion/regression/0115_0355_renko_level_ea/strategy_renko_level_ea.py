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


class RenkoLevel(bt.Indicator):
    lines = ('upper', 'lower', 'color_idx')
    params = dict(size_of_block=30, point_size=0.01)

    def __init__(self):
        self.step_price = self.p.size_of_block * self.p.point_size
        self.eps = self.p.point_size * 0.1
        self.addminperiod(1)

    def _levels(self, price):
        step = self.step_price
        price_round = round(price / step) * step
        price_ceil = math.ceil((price_round + step / 2.0) / step) * step
        price_floor = math.floor((price_round - step / 2.0) / step) * step
        return price_ceil, price_round, price_floor

    def next(self):
        close_price = float(self.data.close[0])
        if len(self) == 1 or not math.isfinite(float(self.lines.upper[-1])) or not math.isfinite(float(self.lines.lower[-1])):
            price_ceil, price_round, price_floor = self._levels(close_price)
            self.lines.upper[0] = price_round
            self.lines.lower[0] = price_floor
            self.lines.color_idx[0] = 0.0
            return
        prev_up = float(self.lines.upper[-1])
        prev_down = float(self.lines.lower[-1])
        prev_color = float(self.lines.color_idx[-1]) if math.isfinite(float(self.lines.color_idx[-1])) else 0.0
        price_ceil, price_round, price_floor = self._levels(close_price)
        upper = prev_up
        lower = prev_down
        color = prev_color
        if prev_down <= close_price <= prev_up:
            pass
        elif close_price < prev_down:
            if abs(price_round - prev_down) > self.eps:
                upper = price_ceil
                lower = price_round
                color = 1.0
        elif close_price > prev_up:
            if abs(price_round - prev_up) > self.eps:
                lower = price_floor
                upper = price_round
                color = 0.0
        self.lines.upper[0] = upper
        self.lines.lower[0] = lower
        self.lines.color_idx[0] = color


class RenkoLevelEAStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        risk_percent=0.0,
        point_size=0.01,
        size_of_block=30,
        reverse=False,
        increase=False,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
    )

    def __init__(self):
        self.data_feed = self.datas[0]
        self.renko = RenkoLevel(self.data_feed, size_of_block=self.p.size_of_block, point_size=self.p.point_size)
        self.order = None
        self.entry_side = None
        self.queued_entry = None
        self.buy_count = 0
        self.sell_count = 0

    def log(self, text):
        dt = bt.num2date(self.data_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_size(self, size):
        bounded = min(max(size, self.p.lot_min), self.p.lot_max)
        steps = round(bounded / self.p.lot_step)
        return min(max(steps * self.p.lot_step, self.p.lot_min), self.p.lot_max)

    def _position_size(self):
        if self.p.fixed_lot > 0:
            return self._round_size(self.p.fixed_lot)
        return self._round_size(self.p.lot_min)

    def _open_side(self, side):
        size = self._position_size()
        self.entry_side = side
        if side == 'long':
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f}')
        else:
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f}')

    def next(self):
        if self.order is not None:
            return
        if self.queued_entry and not self.position:
            queued = self.queued_entry
            self.queued_entry = None
            self._open_side(queued)
            return
        if len(self.renko) < 2:
            return
        current_up = float(self.renko.upper[0])
        prev_up = float(self.renko.upper[-1])
        if not math.isfinite(current_up) or not math.isfinite(prev_up):
            return
        if abs(current_up - prev_up) < self.p.point_size * 0.1:
            return
        signal = None
        if not self.p.reverse:
            signal = 'long' if current_up > prev_up else 'short'
        else:
            signal = 'long' if current_up < prev_up else 'short'
        if signal == 'long':
            if self.position.size < 0:
                self.queued_entry = 'long'
                self.order = self.close()
                self.log(f'CLOSE short renko_up={current_up:.5f} prev_up={prev_up:.5f}')
                return
            if not self.position:
                self._open_side('long')
        else:
            if self.position.size > 0:
                self.queued_entry = 'short'
                self.order = self.close()
                self.log(f'CLOSE long renko_up={current_up:.5f} prev_up={prev_up:.5f}')
                return
            if not self.position:
                self._open_side('short')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if order == self.order and self.entry_side == 'long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self.log(f'ENTRY FILLED LONG price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif order == self.order and self.entry_side == 'short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self.log(f'ENTRY FILLED SHORT price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif not self.position:
                self.log(f'EXIT FILLED price={order.executed.price:.5f} size={order.executed.size:.2f}')
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'ORDER FAILED status={order.getstatusname()}')
                self.queued_entry = None
            self.order = None
            if not self.position:
                self.entry_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
