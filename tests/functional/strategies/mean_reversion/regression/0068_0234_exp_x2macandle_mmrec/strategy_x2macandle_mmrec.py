from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
from collections import deque

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


class X2MACandleApprox(bt.Indicator):
    lines = ('open_value', 'high_value', 'low_value', 'close_value', 'color_state')
    params = dict(length1=12, phase1=15, length2=5, phase2=15, gap=10.0)

    def __init__(self):
        self._length1 = max(1, int(self.p.length1))
        self._length2 = max(2, int(self.p.length2))
        self._phase2 = max(-100, min(100, int(self.p.phase2)))
        base_alpha = 2.0 / (self._length2 + 1.0)
        self._alpha = max(0.01, min(0.95, base_alpha * (1.0 + self._phase2 / 200.0)))
        self._phase_gain = self._phase2 / 200.0
        self._queues = {
            'open': deque(maxlen=self._length1),
            'high': deque(maxlen=self._length1),
            'low': deque(maxlen=self._length1),
            'close': deque(maxlen=self._length1),
        }
        self._states = {
            'open': {'ema1': None, 'ema2': None},
            'high': {'ema1': None, 'ema2': None},
            'low': {'ema1': None, 'ema2': None},
            'close': {'ema1': None, 'ema2': None},
        }
        self.addminperiod(self._length1 + self._length2)

    @staticmethod
    def _finite(value):
        return value is not None and math.isfinite(value)

    def _sma(self, key, value):
        queue = self._queues[key]
        queue.append(float(value))
        if len(queue) < self._length1:
            return None
        return sum(queue) / len(queue)

    def _smooth(self, key, value):
        state = self._states[key]
        if state['ema1'] is None:
            state['ema1'] = value
            state['ema2'] = value
        else:
            state['ema1'] = state['ema1'] + self._alpha * (value - state['ema1'])
            state['ema2'] = state['ema2'] + self._alpha * (state['ema1'] - state['ema2'])
        return state['ema1'] + self._phase_gain * (state['ema1'] - state['ema2'])

    def _stage_value(self, key, line):
        sma_value = self._sma(key, line[0])
        if sma_value is None:
            return None
        return self._smooth(key, sma_value)

    def next(self):
        open_value = self._stage_value('open', self.data.open)
        high_value = self._stage_value('high', self.data.high)
        low_value = self._stage_value('low', self.data.low)
        close_value = self._stage_value('close', self.data.close)
        if not all(self._finite(v) for v in (open_value, high_value, low_value, close_value)):
            self.lines.open_value[0] = float('nan')
            self.lines.high_value[0] = float('nan')
            self.lines.low_value[0] = float('nan')
            self.lines.close_value[0] = float('nan')
            self.lines.color_state[0] = float('nan')
            return
        max_value = max(open_value, close_value, high_value, low_value)
        min_value = min(open_value, close_value, high_value, low_value)
        adjusted_open = open_value
        if len(self) > 1 and abs(float(self.data.open[0]) - float(self.data.close[0])) <= float(self.p.gap):
            prev_close = float(self.lines.close_value[-1])
            if self._finite(prev_close):
                adjusted_open = prev_close
        color_state = 2.0 if adjusted_open < close_value else 0.0 if adjusted_open > close_value else 1.0
        self.lines.open_value[0] = adjusted_open
        self.lines.high_value[0] = max_value
        self.lines.low_value[0] = min_value
        self.lines.close_value[0] = close_value
        self.lines.color_state[0] = color_state


class ExpX2MACandleMMRecStrategy(bt.Strategy):
    params = dict(
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
        buy_loss_trigger=2,
        sell_loss_trigger=2,
        small_mm=0.01,
        mm=0.1,
        mm_mode='LOT',
        stoploss_points=1000,
        takeprofit_points=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        sell_pos_close=True,
        buy_pos_close=True,
        length1=12,
        phase1=15,
        length2=5,
        phase2=15,
        gap=10.0,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.indicator = X2MACandleApprox(
            self.signal_data,
            length1=self.p.length1,
            phase1=self.p.phase1,
            length2=self.p.length2,
            phase2=self.p.phase2,
            gap=self.p.gap,
        )
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.active_side = None
        self.closing_side = None
        self.last_signal_dt = None
        self.mmrec_losses = {'buy': 0, 'sell': 0}

    @staticmethod
    def _finite(value):
        return value is not None and math.isfinite(value)

    def _new_signal_bar(self):
        current = bt.num2date(self.signal_data.datetime[0])
        if self.last_signal_dt == current:
            return False
        self.last_signal_dt = current
        return True

    def _signals(self):
        color_now = self.indicator.color_state[0]
        color_prev = self.indicator.color_state[-1]
        if not self._finite(color_now) or not self._finite(color_prev):
            return False, False, False, False
        buy_open = bool(self.p.buy_pos_open and color_prev != 2.0 and color_now == 2.0)
        sell_open = bool(self.p.sell_pos_open and color_prev != 0.0 and color_now == 0.0)
        buy_close = bool(self.p.buy_pos_close and color_prev != 0.0 and color_now == 0.0)
        sell_close = bool(self.p.sell_pos_close and color_prev != 2.0 and color_now == 2.0)
        return buy_open, sell_open, buy_close, sell_close

    def _loss_adjusted_mm(self, side):
        losses = self.mmrec_losses['buy' if side == 'long' else 'sell']
        trigger = self.p.buy_loss_trigger if side == 'long' else self.p.sell_loss_trigger
        return self.p.small_mm if losses >= trigger else self.p.mm

    def _round_lot(self, size):
        step = self.p.lot_step
        rounded = math.floor(size / step + 1e-12) * step
        rounded = max(self.p.lot_min, rounded)
        rounded = min(self.p.lot_max, rounded)
        return round(rounded, 8)

    def _compute_size(self, side, price):
        mm_value = self._loss_adjusted_mm(side)
        if str(self.p.mm_mode).upper() == 'LOT':
            return self._round_lot(mm_value)
        equity = self.broker.getvalue()
        stop_distance = max(self.p.stoploss_points * self.p.point_size, self.p.point_size)
        risk_amount = equity * max(mm_value, 0.0)
        risk_per_lot = (stop_distance / self.p.point_size) * self.p.contract_multiplier
        if risk_per_lot <= 0:
            return self.p.lot_min
        size = risk_amount / risk_per_lot
        return self._round_lot(size)

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _submit_entry(self, side):
        if self.position or self.entry_order is not None:
            return
        price = float(self.exec_data.close[0])
        if not self._finite(price):
            return
        size = self._compute_size(side, price)
        if size <= 0:
            return
        stop_distance = self.p.stoploss_points * self.p.point_size
        take_distance = self.p.takeprofit_points * self.p.point_size
        if side == 'long':
            sl = price - stop_distance
            tp = price + take_distance
            orders = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
        else:
            sl = price + stop_distance
            tp = price - take_distance
            orders = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
        self.entry_order, self.stop_order, self.limit_order = orders
        self.active_side = side

    def _submit_close(self):
        if not self.position or self.close_order is not None:
            return
        self._cancel_exit_orders()
        self.closing_side = self.active_side
        self.close_order = self.close()

    def next(self):
        min_bars = max(self.p.length1 + self.p.length2 + 2, 20)
        if len(self.signal_data) < min_bars:
            return
        if not self.position and self.pending_reverse and self.entry_order is None and self.close_order is None:
            side = self.pending_reverse
            self.pending_reverse = None
            self._submit_entry(side)
            return
        if not self._new_signal_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        if self.position:
            if self.position.size > 0 and buy_close:
                self.pending_reverse = 'short' if sell_open else None
                self._submit_close()
            elif self.position.size < 0 and sell_close:
                self.pending_reverse = 'long' if buy_open else None
                self._submit_close()
            return
        if buy_open:
            self._submit_entry('long')
        elif sell_open:
            self._submit_entry('short')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
            elif order == self.stop_order:
                self.stop_order = None
                self.limit_order = None
            elif order == self.limit_order:
                self.limit_order = None
                self.stop_order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
                self.stop_order = None
                self.limit_order = None
            elif order == self.close_order:
                self.close_order = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        side = self.closing_side or self.active_side or ('long' if trade.long else 'short')
        key = 'buy' if side == 'long' else 'sell'
        if trade.pnlcomm < 0:
            self.mmrec_losses[key] += 1
        else:
            self.mmrec_losses[key] = 0
        if not self.position:
            self.active_side = None
            self.closing_side = None
