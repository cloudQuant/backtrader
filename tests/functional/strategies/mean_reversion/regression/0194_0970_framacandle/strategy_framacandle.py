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


class FramaSeries(bt.Indicator):
    lines = ('frama',)
    params = dict(period=14)

    def __init__(self):
        self.addminperiod(max(int(self.p.period), 2))

    def next(self):
        period = max(int(self.p.period), 2)
        half = max(period // 2, 1)
        window = [float(self.data[-i]) for i in range(period - 1, -1, -1)]
        if len(window) < period:
            self.lines.frama[0] = float(self.data[0])
            return
        first = window[:half]
        second = window[-half:]
        n1 = (max(first) - min(first)) / float(half)
        n2 = (max(second) - min(second)) / float(half)
        n3 = (max(window) - min(window)) / float(period)
        if n1 > 0.0 and n2 > 0.0 and n3 > 0.0:
            dim = (math.log(n1 + n2) - math.log(n3)) / math.log(2.0)
        else:
            dim = 1.0
        alpha = math.exp(-4.6 * (dim - 1.0))
        alpha = min(max(alpha, 0.01), 1.0)
        prev = float(self.lines.frama[-1]) if len(self) > 0 else float(self.data[0])
        self.lines.frama[0] = alpha * float(self.data[0]) + (1.0 - alpha) * prev


class FramaLinesIndicator(bt.Indicator):
    lines = ('o', 'h', 'l', 'c', 'color')
    params = dict(period=14)

    def __init__(self):
        self.addminperiod(int(self.p.period) + 2)
        self.frama_open = FramaSeries(self.data.open, period=int(self.p.period))
        self.frama_high = FramaSeries(self.data.high, period=int(self.p.period))
        self.frama_low = FramaSeries(self.data.low, period=int(self.p.period))
        self.frama_close = FramaSeries(self.data.close, period=int(self.p.period))

    def next(self):
        o = float(self.frama_open[0])
        h = float(self.frama_high[0])
        l = float(self.frama_low[0])
        c = float(self.frama_close[0])
        mx = max(o, c)
        mn = min(o, c)
        h = max(mx, h)
        l = min(mn, l)
        color = 1
        if o < c:
            color = 2
        elif o > c:
            color = 0
        self.lines.o[0] = o
        self.lines.h[0] = h
        self.lines.l[0] = l
        self.lines.c[0] = c
        self.lines.color[0] = color


class FramaCandleStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        risk_percent=0.0,
        point=0.01,
        stop_loss_points=1000,
        take_profit_points=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        frama_period=14,
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = FramaLinesIndicator(self.signal_feed, period=self.p.frama_period)
        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.entry_side = None
        self.pending_entry_direction = 0
        self.pending_reverse_direction = 0
        self.last_signal_dt = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.warmup = int(self.p.frama_period) + int(self.p.signal_bar) + 4

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
        stop_distance = self.p.stop_loss_points * self.p.point
        if stop_distance <= 0 or self.p.risk_percent <= 0:
            return self._round_size(self.p.lot_min)
        risk_money = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        raw_size = risk_money / (stop_distance * self.p.contract_multiplier)
        return self._round_size(raw_size)

    def _buffer_value(self, line, signal_bar, previous=False):
        shift = (int(signal_bar) - 1) + (1 if previous else 0)
        if len(line.array) <= shift:
            return None
        value = float(line[-shift] if shift else line[0])
        if not math.isfinite(value):
            return None
        return value

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stop_loss_points * self.p.point
        take_distance = self.p.take_profit_points * self.p.point
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price + take_distance if self.p.take_profit_points > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price - take_distance if self.p.take_profit_points > 0 else None

    def _clear_risk(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    def _submit_entry(self, direction, reason):
        size = self._position_size()
        if size <= 0:
            return False
        self.pending_entry_direction = direction
        if direction > 0:
            self.entry_side = 'long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} reason={reason}')
        else:
            self.entry_side = 'short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} reason={reason}')
        return True

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.data0_feed.low[0])
        high = float(self.data0_feed.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.pending_reverse_direction = 0
                self.order = self.close()
                self.log(f'CLOSE long protective stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.pending_reverse_direction = 0
                self.order = self.close()
                self.log(f'CLOSE long take_profit={self.take_profit_price:.5f}')
                return True
            return False
        if self.stop_price is not None and high >= self.stop_price:
            self.pending_reverse_direction = 0
            self.order = self.close()
            self.log(f'CLOSE short protective stop={self.stop_price:.5f}')
            return True
        if self.take_profit_price is not None and low <= self.take_profit_price:
            self.pending_reverse_direction = 0
            self.order = self.close()
            self.log(f'CLOSE short take_profit={self.take_profit_price:.5f}')
            return True
        return False

    def next(self):
        self.bar_num += 1
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        if len(self.signal_feed) < self.warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        trend_now = self._buffer_value(self.indicator.color, self.p.signal_bar)
        trend_prev = self._buffer_value(self.indicator.color, self.p.signal_bar, previous=True)
        if None in (trend_now, trend_prev):
            if len(self.signal_feed) < 2:
                return
            delta = float(self.signal_feed.close[0]) - float(self.signal_feed.close[-1])
            trend_now = 2 if delta > 0 else 0
            trend_prev = 1
        self.last_signal_dt = signal_dt
        trend_now = int(round(trend_now))
        trend_prev = int(round(trend_prev))
        buy_open = trend_prev == 2 and self.p.buy_pos_open and trend_now < 2
        sell_close = trend_prev == 2 and self.p.sell_pos_close
        sell_open = trend_prev == 0 and self.p.sell_pos_open and trend_now > 0
        buy_close = trend_prev == 0 and self.p.buy_pos_close
        if not buy_open and not sell_open and not self.position:
            buy_open = self.p.buy_pos_open and trend_now > trend_prev
            sell_open = self.p.sell_pos_open and trend_now < trend_prev
        if not buy_open and not sell_open and not self.position:
            buy_open = self.p.buy_pos_open and trend_now >= 1
            sell_open = self.p.sell_pos_open and trend_now < 1
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
                self.log(f'CLOSE long color_prev={trend_prev} color_now={trend_now}')
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
                self.log(f'CLOSE short color_prev={trend_prev} color_now={trend_now}')
            return
        if buy_open:
            self._submit_entry(1, f'color_prev={trend_prev} color_now={trend_now}')
            return
        if sell_open:
            self._submit_entry(-1, f'color_prev={trend_prev} color_now={trend_now}')
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            self.pending_entry_direction = 0
            self.pending_reverse_direction = 0
            if not self.position:
                self.entry_side = None
            return
        if order.status != order.Completed:
            return
        self.completed_order_count += 1
        if self.pending_entry_direction == 1 and order.isbuy() and self.position.size > 0:
            self.buy_count += 1
            self.entry_price = order.executed.price
            self._set_entry_risk(self.entry_price, 1)
            self.pending_entry_direction = 0
            self.log(f'ENTRY FILLED LONG price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            return
        if self.pending_entry_direction == -1 and order.issell() and self.position.size < 0:
            self.sell_count += 1
            self.entry_price = order.executed.price
            self._set_entry_risk(self.entry_price, -1)
            self.pending_entry_direction = 0
            self.log(f'ENTRY FILLED SHORT price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            return
        if not self.position:
            self._clear_risk()
            self.log(f'EXIT FILLED price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            self.entry_side = None
            reverse_direction = self.pending_reverse_direction
            self.pending_reverse_direction = 0
            if reverse_direction != 0:
                self._submit_entry(reverse_direction, 'reverse after FrAMA candle color change')
            return
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self._clear_risk()
            self.entry_side = None
