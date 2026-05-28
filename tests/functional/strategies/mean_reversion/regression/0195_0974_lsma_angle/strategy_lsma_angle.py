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


class LsmaAngleIndicator(bt.Indicator):
    lines = ('angle', 'color_index')
    params = dict(lsma_period=25, angle_threshold=15, start_shift=4, end_shift=0)

    def __init__(self):
        needed = int(max(self.p.lsma_period + self.p.start_shift, self.p.lsma_period + self.p.end_shift)) + 2
        self.addminperiod(needed)
        self._m_factor = None

    def _lsma(self, shift):
        period = int(self.p.lsma_period)
        values = [float(self.data.close[-(shift + i)]) for i in range(period)]
        x = list(range(period))
        x_mean = sum(x) / period
        y_mean = sum(values) / period
        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, values))
        denominator = sum((xi - x_mean) ** 2 for xi in x)
        slope = numerator / denominator if denominator else 0.0
        intercept = y_mean - slope * x_mean
        return intercept + slope * (period - 1)

    def _ensure_factor(self):
        if self._m_factor is not None:
            return
        point = float(getattr(self.data, '_dataname', None).attrs['point']) if hasattr(getattr(self.data, '_dataname', None), 'attrs') and 'point' in self.data._dataname.attrs else None
        if point is None or point <= 0:
            close0 = float(self.data.close[0]) if len(self.data) else 0.0
            point = 0.01 if abs(close0) >= 10 and abs(close0) < 1000 else 0.0001
        shift_diff = float(int(self.p.start_shift) - int(self.p.end_shift))
        self._m_factor = (1000.0 if abs(float(self.data.close[0])) >= 10 and abs(float(self.data.close[0])) < 1000 else 100000.0) / shift_diff

    def next(self):
        if int(self.p.end_shift) >= int(self.p.start_shift):
            self.lines.angle[0] = 0.0
            self.lines.color_index[0] = 2
            return
        self._ensure_factor()
        end_ma = self._lsma(int(self.p.end_shift))
        start_ma = self._lsma(int(self.p.start_shift))
        angle = self._m_factor * (end_ma - start_ma) / 2.0
        self.lines.angle[0] = angle
        clr = 2
        threshold = float(self.p.angle_threshold)
        prev_angle = float(self.lines.angle[-1]) if len(self) > 0 and math.isfinite(float(self.lines.angle[-1])) else angle
        if angle > threshold:
            if angle > prev_angle:
                clr = 4
            elif angle < prev_angle:
                clr = 3
        if angle < -threshold:
            if angle < prev_angle:
                clr = 0
            elif angle > prev_angle:
                clr = 1
        self.lines.color_index[0] = clr


class LsmaAngleStrategy(bt.Strategy):
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
        lsma_period=25,
        angle_threshold=15,
        start_shift=4,
        end_shift=0,
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = LsmaAngleIndicator(
            self.signal_feed,
            lsma_period=self.p.lsma_period,
            angle_threshold=self.p.angle_threshold,
            start_shift=self.p.start_shift,
            end_shift=self.p.end_shift,
        )
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
        self.warmup = int(max(self.p.lsma_period + self.p.start_shift, self.p.lsma_period + self.p.end_shift)) + int(self.p.signal_bar) + 4

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
        self.last_signal_dt = signal_dt
        if len(self.signal_feed) < self.warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        value_now = self._buffer_value(self.indicator.color_index, self.p.signal_bar)
        value_prev = self._buffer_value(self.indicator.color_index, self.p.signal_bar, previous=True)
        if None in (value_now, value_prev):
            return
        value_now = int(round(value_now))
        value_prev = int(round(value_prev))
        buy_open = self.p.buy_pos_open and value_prev == 4 and value_now < 4
        sell_close = self.p.sell_pos_close and value_prev > 1
        sell_open = self.p.sell_pos_open and value_prev == 0 and value_now > 0
        buy_close = self.p.buy_pos_close and value_prev < 2
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
                self.log(f'CLOSE long color_prev={value_prev} color_now={value_now}')
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
                self.log(f'CLOSE short color_prev={value_prev} color_now={value_now}')
            return
        if buy_open:
            self._submit_entry(1, f'color_prev={value_prev} color_now={value_now}')
            return
        if sell_open:
            self._submit_entry(-1, f'color_prev={value_prev} color_now={value_now}')
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
                self._submit_entry(reverse_direction, 'reverse after color transition')
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
