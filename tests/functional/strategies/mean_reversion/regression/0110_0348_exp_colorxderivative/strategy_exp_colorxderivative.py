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


class ColorXDerivative(bt.Indicator):
    lines = ('value', 'color_idx')
    params = dict(i_slowing=34, xlength=15)

    def __init__(self):
        self.addminperiod(max(self.p.i_slowing + 2, self.p.xlength + 2))

    def _price(self, ago=0):
        return (float(self.data.high[ago]) + float(self.data.low[ago]) + 2.0 * float(self.data.close[ago])) / 4.0

    def next(self):
        der = 100.0 * (self._price(0) - self._price(-self.p.i_slowing)) / float(self.p.i_slowing)
        window = [100.0 * (self._price(-i) - self._price(-(i + self.p.i_slowing))) / float(self.p.i_slowing) for i in range(self.p.xlength)]
        smooth = sum(window) / float(len(window)) if window else der
        self.lines.value[0] = smooth
        prev = float(self.lines.value[-1]) if len(self) > 1 else smooth
        color = 2.0
        if smooth > 0:
            color = 0.0 if prev <= smooth else 1.0
        elif smooth < 0:
            color = 4.0 if prev >= smooth else 3.0
        self.lines.color_idx[0] = color


class ExpColorXDerivativeStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        risk_percent=0.0,
        point_size=0.01,
        stoploss_pips=1000,
        takeprofit_pips=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        i_slowing=34,
        xlength=15,
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[1]
        self.ind = ColorXDerivative(self.signal_feed, i_slowing=self.p.i_slowing, xlength=self.p.xlength)
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None
        self.buy_count = 0
        self.sell_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_size(self, size):
        bounded = min(max(size, self.p.lot_min), self.p.lot_max)
        steps = round(bounded / self.p.lot_step)
        return min(max(steps * self.p.lot_step, self.p.lot_min), self.p.lot_max)

    def _position_size(self):
        if self.p.fixed_lot > 0:
            return self._round_size(self.p.fixed_lot)
        stop_distance = self.p.stoploss_pips * self.p.point_size
        if stop_distance <= 0 or self.p.risk_percent <= 0:
            return self._round_size(self.p.lot_min)
        risk_money = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        raw_size = risk_money / (stop_distance * self.p.contract_multiplier)
        return self._round_size(raw_size)

    def _line_value(self, line, signal_bar, previous=False):
        shift = (int(signal_bar) - 1) + (1 if previous else 0)
        if len(line.array) <= shift:
            return None
        value = float(line[-shift] if shift else line[0])
        if not math.isfinite(value):
            return None
        return value

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stoploss_pips > 0 else None
            self.take_profit_price = price + take_distance if self.p.takeprofit_pips > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stoploss_pips > 0 else None
            self.take_profit_price = price - take_distance if self.p.takeprofit_pips > 0 else None

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.data0_feed.low[0])
        high = float(self.data0_feed.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                self.log(f'CLOSE long protective stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                self.log(f'CLOSE long take_profit={self.take_profit_price:.5f}')
                return True
            return False
        if self.stop_price is not None and high >= self.stop_price:
            self.order = self.close()
            self.log(f'CLOSE short protective stop={self.stop_price:.5f}')
            return True
        if self.take_profit_price is not None and low <= self.take_profit_price:
            self.order = self.close()
            self.log(f'CLOSE short take_profit={self.take_profit_price:.5f}')
            return True
        return False

    def next(self):
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        warmup = self.p.i_slowing + self.p.xlength + self.p.signal_bar + 2
        if len(self.signal_feed) < warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        color_now = self._line_value(self.ind.color_idx, self.p.signal_bar)
        color_prev = self._line_value(self.ind.color_idx, self.p.signal_bar, previous=True)
        value_now = self._line_value(self.ind.value, self.p.signal_bar)
        if None in (color_now, color_prev, value_now):
            return
        buy_open = self.p.buy_pos_open and ((color_prev == 0.0 and color_now != 0.0) or (color_prev == 3.0 and color_now in (4.0, 2.0)))
        sell_close = self.p.sell_pos_close and color_prev in (0.0, 3.0)
        sell_open = self.p.sell_pos_open and ((color_prev == 4.0 and color_now != 4.0) or (color_prev == 1.0 and color_now in (0.0, 2.0)))
        buy_close = self.p.buy_pos_close and color_prev in (1.0, 4.0)
        if self.position.size > 0 and buy_close:
            self.order = self.close()
            self.log(f'CLOSE long color_now={color_now} color_prev={color_prev} value={value_now:.5f}')
            return
        if self.position.size < 0 and sell_close:
            self.order = self.close()
            self.log(f'CLOSE short color_now={color_now} color_prev={color_prev} value={value_now:.5f}')
            return
        if self.position:
            return
        size = self._position_size()
        if buy_open:
            self.entry_side = 'long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} color_now={color_now} color_prev={color_prev} value={value_now:.5f}')
        elif sell_open:
            self.entry_side = 'short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} color_now={color_now} color_prev={color_prev} value={value_now:.5f}')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if order == self.order and self.entry_side == 'long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self._set_entry_risk(order.executed.price, 1)
                self.log(f'ENTRY FILLED LONG price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif order == self.order and self.entry_side == 'short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self._set_entry_risk(order.executed.price, -1)
                self.log(f'ENTRY FILLED SHORT price={order.executed.price:.5f} size={order.executed.size:.2f}')
            elif not self.position:
                self._clear_risk()
                self.log(f'EXIT FILLED price={order.executed.price:.5f} size={order.executed.size:.2f}')
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            if not self.position:
                self.entry_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self._clear_risk()
            self.entry_side = None
