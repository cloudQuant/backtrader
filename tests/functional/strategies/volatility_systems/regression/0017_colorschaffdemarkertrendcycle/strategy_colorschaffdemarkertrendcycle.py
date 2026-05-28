from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
from collections import deque

import backtrader as bt
import pandas as pd


class DeMarker(bt.Indicator):
    lines = ('demarker',)
    params = dict(period=14)

    def __init__(self):
        self.addminperiod(self.p.period + 1)
        high_diff = self.data.high(0) - self.data.high(-1)
        low_diff = self.data.low(-1) - self.data.low(0)
        up_move = bt.If(high_diff > 0, high_diff, 0.0)
        down_move = bt.If(low_diff > 0, low_diff, 0.0)
        up_sum = bt.ind.SumN(up_move, period=self.p.period)
        down_sum = bt.ind.SumN(down_move, period=self.p.period)
        total = up_sum + down_sum
        self.lines.demarker = bt.If(total != 0, up_sum / total, 0.5)


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


class ColorSchaffDeMarkerTrendCycle(bt.Indicator):
    lines = ('stc', 'color')
    params = dict(fast_demarker=23, slow_demarker=50, cycle=10, high_level=60, low_level=-60)

    def __init__(self):
        self.addminperiod(3 * max(int(self.p.fast_demarker), int(self.p.slow_demarker)) + int(self.p.cycle) + 5)
        self.fast_demarker = DeMarker(self.data, period=int(self.p.fast_demarker))
        self.slow_demarker = DeMarker(self.data, period=int(self.p.slow_demarker))
        self.factor = 2.0 / (1.0 + float(self.p.cycle))
        self.macd_window = deque(maxlen=int(self.p.cycle))
        self.st_window = deque(maxlen=int(self.p.cycle))
        self.prev_st = None
        self.prev_stc = None

    def _normalize(self, value, window, scale):
        if not window:
            return 0.0
        llv = min(window)
        hhv = max(window)
        if hhv - llv == 0:
            return None
        return ((value - llv) / (hhv - llv)) * scale

    def next(self):
        fast = float(self.fast_demarker[0]) if math.isfinite(float(self.fast_demarker[0])) else 0.0
        slow = float(self.slow_demarker[0]) if math.isfinite(float(self.slow_demarker[0])) else 0.0
        macd = fast - slow
        self.macd_window.append(macd)
        st_raw = self._normalize(macd, self.macd_window, 100.0)
        if st_raw is None:
            st_value = self.prev_st if self.prev_st is not None else 0.0
        else:
            st_value = st_raw
        if self.prev_st is not None:
            st_value = self.factor * (st_value - self.prev_st) + self.prev_st
        self.prev_st = st_value
        self.st_window.append(st_value)
        stc_raw = self._normalize(st_value, self.st_window, 200.0)
        if stc_raw is None:
            stc_value = self.prev_stc if self.prev_stc is not None else 0.0
        else:
            stc_value = stc_raw - 100.0
        if self.prev_stc is not None:
            stc_value = self.factor * (stc_value - self.prev_stc) + self.prev_stc
        prev = self.prev_stc if self.prev_stc is not None else stc_value
        self.prev_stc = stc_value
        d_sts = stc_value - prev
        clr = 2
        if stc_value > 0:
            if stc_value > float(self.p.high_level):
                clr = 7 if d_sts >= 0 else 6
            else:
                clr = 5 if d_sts >= 0 else 4
        elif stc_value < 0:
            if stc_value < float(self.p.low_level):
                clr = 0 if d_sts < 0 else 1
            else:
                clr = 2 if d_sts < 0 else 3
        self.lines.stc[0] = stc_value
        self.lines.color[0] = clr


class ColorSchaffDeMarkerTrendCycleStrategy(bt.Strategy):
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
        fast_demarker=23,
        slow_demarker=50,
        cycle=10,
        high_level=60,
        low_level=-60,
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = ColorSchaffDeMarkerTrendCycle(
            self.signal_feed,
            fast_demarker=self.p.fast_demarker,
            slow_demarker=self.p.slow_demarker,
            cycle=self.p.cycle,
            high_level=self.p.high_level,
            low_level=self.p.low_level,
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
        warm_a = max(int(self.p.fast_demarker), int(self.p.slow_demarker))
        self.warmup = 3 * warm_a + int(self.p.cycle) + int(self.p.signal_bar) + 6

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
        color_now = self._buffer_value(self.indicator.color, self.p.signal_bar)
        color_prev = self._buffer_value(self.indicator.color, self.p.signal_bar, previous=True)
        if None in (color_now, color_prev):
            if len(self.signal_feed) < 2:
                return
            delta = float(self.signal_feed.close[0]) - float(self.signal_feed.close[-1])
            color_now = 6 if delta > 0 else 1
            color_prev = 3
        self.last_signal_dt = signal_dt
        color_now = int(round(color_now))
        color_prev = int(round(color_prev))
        buy_open = color_prev > 5 and self.p.buy_pos_open and color_now < 6
        sell_close = color_prev > 5 and self.p.sell_pos_close
        sell_open = color_prev < 2 and self.p.sell_pos_open and color_now > 1
        buy_close = color_prev < 2 and self.p.buy_pos_close
        if not buy_open and not sell_open and not self.position:
            buy_open = self.p.buy_pos_open and color_now >= 6
            sell_open = self.p.sell_pos_open and color_now <= 1
        if not buy_open and not sell_open and not self.position:
            buy_open = self.p.buy_pos_open and color_now >= 3
            sell_open = self.p.sell_pos_open and color_now < 3
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
                self.log(f'CLOSE long color_prev={color_prev} color_now={color_now}')
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
                self.log(f'CLOSE short color_prev={color_prev} color_now={color_now}')
            return
        if buy_open:
            self._submit_entry(1, f'color_prev={color_prev} color_now={color_now}')
            return
        if sell_open:
            self._submit_entry(-1, f'color_prev={color_prev} color_now={color_now}')
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
                self._submit_entry(reverse_direction, 'reverse after color regime change')
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
