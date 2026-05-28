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


class BrainTrend2Indicator(bt.Indicator):
    lines = ('color_state',)
    params = dict(atr_period=7, point_size=0.01)

    def __init__(self):
        self._period = max(1, int(self.p.atr_period))
        self._cecf = 0.7
        self._trs = deque(maxlen=self._period)
        self._river = None
        self._emaxtra = None
        self.addminperiod(self._period + 2)

    @staticmethod
    def _finite(value):
        return value is not None and math.isfinite(value)

    def next(self):
        prev_close = float(self.data.close[-1]) if len(self.data) > 1 else float(self.data.close[0])
        spread = float(getattr(self.data, 'spread')[0]) * self.p.point_size if hasattr(self.data, 'spread') else 0.0
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        open_ = float(self.data.open[0])
        close = float(self.data.close[0])
        tr = spread + high - low
        tr = max(tr, abs(spread + high - prev_close), abs(low - prev_close))
        self._trs.append(tr)
        if len(self._trs) < self._period:
            self.lines.color_state[0] = float('nan')
            return
        weights = list(range(self._period, 0, -1))
        atr = 2.0 * sum(w * v for w, v in zip(weights, reversed(self._trs))) / (self._period * (self._period + 1.0))
        widcha = self._cecf * atr
        if self._river is None:
            prev2_close = float(self.data.close[-2]) if len(self.data) > 2 else prev_close
            self._river = prev2_close > prev_close
            self._emaxtra = prev_close
        if self._river and low < self._emaxtra - widcha:
            self._river = False
            self._emaxtra = spread + high
        if (not self._river) and spread + high > self._emaxtra + widcha:
            self._river = True
            self._emaxtra = low
        if self._river and low > self._emaxtra:
            self._emaxtra = low
        if (not self._river) and spread + high < self._emaxtra:
            self._emaxtra = spread + high
        if self._river:
            color = 0.0 if open_ <= close else 1.0
        else:
            color = 4.0 if open_ >= close else 3.0
        self.lines.color_state[0] = color


class AbsolutelyNoLagLwmaIndicator(bt.Indicator):
    lines = ('line_value', 'color_state')
    params = dict(length=7)

    def __init__(self):
        self._length = max(1, int(self.p.length))
        self._price_window = deque(maxlen=self._length)
        self._lwma_window = deque(maxlen=self._length)
        self.addminperiod(self._length * 2)

    def _weighted_ma(self, values):
        weights = list(range(len(values), 0, -1))
        total = sum(weights)
        return sum(w * v for w, v in zip(weights, reversed(values))) / total

    def next(self):
        price = float(self.data.close[0])
        self._price_window.append(price)
        if len(self._price_window) < self._length:
            self.lines.line_value[0] = float('nan')
            self.lines.color_state[0] = float('nan')
            return
        lwma1 = self._weighted_ma(self._price_window)
        self._lwma_window.append(lwma1)
        if len(self._lwma_window) < self._length:
            self.lines.line_value[0] = float('nan')
            self.lines.color_state[0] = float('nan')
            return
        lwma2 = self._weighted_ma(self._lwma_window)
        color = 1.0
        prev = self.lines.line_value[-1] if len(self) > 0 else float('nan')
        if prev == prev:
            if prev < lwma2:
                color = 2.0
            elif prev > lwma2:
                color = 0.0
        self.lines.line_value[0] = lwma2
        self.lines.color_state[0] = color


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


class ExpBrainTrend2AbsolutelyNoLagLwmaX2MACandleMMRecStrategy(bt.Strategy):
    params = dict(
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
        a_buy_loss_trigger=2,
        a_sell_loss_trigger=2,
        a_small_mm=0.01,
        a_mm=0.1,
        a_mm_mode='LOT',
        a_stoploss_points=2000,
        a_takeprofit_points=5000,
        a_buy_pos_open=True,
        a_sell_pos_open=True,
        a_sell_pos_close=True,
        a_buy_pos_close=True,
        a_atr_period=7,
        b_buy_loss_trigger=2,
        b_sell_loss_trigger=2,
        b_small_mm=0.01,
        b_mm=0.1,
        b_mm_mode='LOT',
        b_stoploss_points=2000,
        b_takeprofit_points=5000,
        b_buy_pos_open=True,
        b_sell_pos_open=True,
        b_sell_pos_close=True,
        b_buy_pos_close=True,
        b_length=7,
        c_buy_loss_trigger=2,
        c_sell_loss_trigger=2,
        c_small_mm=0.01,
        c_mm=0.1,
        c_mm_mode='LOT',
        c_stoploss_points=1000,
        c_takeprofit_points=2000,
        c_buy_pos_open=True,
        c_sell_pos_open=True,
        c_sell_pos_close=True,
        c_buy_pos_close=True,
        c_length1=12,
        c_phase1=15,
        c_length2=5,
        c_phase2=15,
        c_gap=10.0,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.a_indicator = BrainTrend2Indicator(self.signal_data, atr_period=self.p.a_atr_period, point_size=self.p.point_size)
        self.b_indicator = AbsolutelyNoLagLwmaIndicator(self.signal_data, length=self.p.b_length)
        self.c_indicator = X2MACandleApprox(
            self.signal_data,
            length1=self.p.c_length1,
            phase1=self.p.c_phase1,
            length2=self.p.c_length2,
            phase2=self.p.c_phase2,
            gap=self.p.c_gap,
        )
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.pending_entry_system = None
        self.pending_entry_side = None
        self.active_system = None
        self.active_side = None
        self.closing_system = None
        self.closing_side = None
        self.last_signal_dt = None
        self.mmrec_losses = {
            'A_buy': 0,
            'A_sell': 0,
            'B_buy': 0,
            'B_sell': 0,
            'C_buy': 0,
            'C_sell': 0,
        }

    def log(self, text):
        dt = bt.num2date(self.exec_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def prenext(self):
        self.next()

    def _normalize_lot(self, lot):
        lot = min(max(lot, self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def _new_signal_bar(self):
        current = bt.num2date(self.signal_data.datetime[0])
        if self.last_signal_dt == current:
            return False
        self.last_signal_dt = current
        return True

    @staticmethod
    def _has_value(value):
        return value is not None and math.isfinite(value)

    def _a_signals(self):
        color_now = self.a_indicator.color_state[0]
        color_prev = self.a_indicator.color_state[-1] if len(self.a_indicator) > 1 else float('nan')
        buy_open = self.p.a_buy_pos_open and self._has_value(color_now) and self._has_value(color_prev) and color_now < 2.0 and color_prev > 1.0
        sell_open = self.p.a_sell_pos_open and self._has_value(color_now) and self._has_value(color_prev) and color_now > 2.0 and color_prev < 3.0
        buy_close = self.p.a_buy_pos_close and self._has_value(color_now) and color_now > 2.0
        sell_close = self.p.a_sell_pos_close and self._has_value(color_now) and color_now < 2.0
        return {'buy_open': buy_open, 'sell_open': sell_open, 'buy_close': buy_close, 'sell_close': sell_close}

    def _b_signals(self):
        color_now = self.b_indicator.color_state[0]
        color_prev = self.b_indicator.color_state[-1] if len(self.b_indicator) > 1 else float('nan')
        buy_open = self.p.b_buy_pos_open and self._has_value(color_now) and color_now == 2.0 and (not self._has_value(color_prev) or color_prev != 2.0)
        sell_open = self.p.b_sell_pos_open and self._has_value(color_now) and color_now == 0.0 and (not self._has_value(color_prev) or color_prev != 0.0)
        buy_close = self.p.b_buy_pos_close and self._has_value(color_now) and color_now == 0.0
        sell_close = self.p.b_sell_pos_close and self._has_value(color_now) and color_now == 2.0
        return {'buy_open': buy_open, 'sell_open': sell_open, 'buy_close': buy_close, 'sell_close': sell_close}

    def _c_signals(self):
        color_now = self.c_indicator.color_state[0]
        color_prev = self.c_indicator.color_state[-1] if len(self.c_indicator) > 1 else float('nan')
        buy_open = self.p.c_buy_pos_open and self._has_value(color_now) and color_now == 2.0 and (not self._has_value(color_prev) or color_prev != 2.0)
        sell_open = self.p.c_sell_pos_open and self._has_value(color_now) and color_now == 0.0 and (not self._has_value(color_prev) or color_prev != 0.0)
        buy_close = self.p.c_buy_pos_close and self._has_value(color_now) and color_now == 0.0
        sell_close = self.p.c_sell_pos_close and self._has_value(color_now) and color_now == 2.0
        return {'buy_open': buy_open, 'sell_open': sell_open, 'buy_close': buy_close, 'sell_close': sell_close}

    def _mm_key(self, system, side):
        return f'{system}_{"buy" if side == "long" else "sell"}'

    def _current_mm(self, system, side):
        key = self._mm_key(system, side)
        losses = self.mmrec_losses[key]
        if system == 'A':
            trigger = self.p.a_buy_loss_trigger if side == 'long' else self.p.a_sell_loss_trigger
            mm = self.p.a_small_mm if losses >= trigger else self.p.a_mm
            mode = self.p.a_mm_mode
            stop_points = self.p.a_stoploss_points
            take_points = self.p.a_takeprofit_points
        elif system == 'B':
            trigger = self.p.b_buy_loss_trigger if side == 'long' else self.p.b_sell_loss_trigger
            mm = self.p.b_small_mm if losses >= trigger else self.p.b_mm
            mode = self.p.b_mm_mode
            stop_points = self.p.b_stoploss_points
            take_points = self.p.b_takeprofit_points
        else:
            trigger = self.p.c_buy_loss_trigger if side == 'long' else self.p.c_sell_loss_trigger
            mm = self.p.c_small_mm if losses >= trigger else self.p.c_mm
            mode = self.p.c_mm_mode
            stop_points = self.p.c_stoploss_points
            take_points = self.p.c_takeprofit_points
        return mm, mode, stop_points, take_points

    def _size_for_entry(self, system, side):
        mm, mode, stop_points, _ = self._current_mm(system, side)
        if str(mode).upper() == 'LOT':
            return self._normalize_lot(mm)
        risk_cash = self.broker.getvalue() * mm
        stop_distance = stop_points * self.p.point_size
        raw = risk_cash / max(stop_distance * self.p.contract_multiplier, self.p.point_size)
        return self._normalize_lot(raw)

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _submit_entry(self, system, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = self._size_for_entry(system, side)
        if size <= 0:
            return
        price = self.exec_data.close[0]
        _, _, stop_points, take_points = self._current_mm(system, side)
        stop_distance = stop_points * self.p.point_size
        take_distance = take_points * self.p.point_size
        if side == 'long':
            sl = price - stop_distance
            tp = price + take_distance
            orders = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
        else:
            sl = price + stop_distance
            tp = price - take_distance
            orders = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
        self.entry_order, self.stop_order, self.limit_order = orders
        self.pending_entry_system = system
        self.pending_entry_side = side
        self.log(f'OPEN {system} {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self.closing_system = self.active_system
        self.closing_side = self.active_side
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE system={self.active_system} side={self.active_side} reason={reason} reverse={reverse}')

    def next(self):
        min_bars = max(self.p.a_atr_period + 3, self.p.b_length * 2 + 3, self.p.c_length1 + self.p.c_length2 + 3)
        if len(self.signal_data) < min_bars:
            return
        if not self._new_signal_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        a = self._a_signals()
        b = self._b_signals()
        c = self._c_signals()
        if self.position:
            if self.active_system == 'A':
                if self.active_side == 'long' and a['buy_close']:
                    reverse = ('A', 'short') if a['sell_open'] else None
                    self._submit_close('A close long', reverse=reverse)
                elif self.active_side == 'short' and a['sell_close']:
                    reverse = ('A', 'long') if a['buy_open'] else None
                    self._submit_close('A close short', reverse=reverse)
            elif self.active_system == 'B':
                if self.active_side == 'long' and b['buy_close']:
                    reverse = ('B', 'short') if b['sell_open'] else None
                    self._submit_close('B close long', reverse=reverse)
                elif self.active_side == 'short' and b['sell_close']:
                    reverse = ('B', 'long') if b['buy_open'] else None
                    self._submit_close('B close short', reverse=reverse)
            elif self.active_system == 'C':
                if self.active_side == 'long' and c['buy_close']:
                    reverse = ('C', 'short') if c['sell_open'] else None
                    self._submit_close('C close long', reverse=reverse)
                elif self.active_side == 'short' and c['sell_close']:
                    reverse = ('C', 'long') if c['buy_open'] else None
                    self._submit_close('C close short', reverse=reverse)
            return
        if a['buy_open']:
            self._submit_entry('A', 'long', 'BrainTrend2 buy')
        elif a['sell_open']:
            self._submit_entry('A', 'short', 'BrainTrend2 sell')
        elif b['buy_open']:
            self._submit_entry('B', 'long', 'AbsolutelyNoLagLwma buy')
        elif b['sell_open']:
            self._submit_entry('B', 'short', 'AbsolutelyNoLagLwma sell')
        elif c['buy_open']:
            self._submit_entry('C', 'long', 'X2MACandle buy')
        elif c['sell_open']:
            self._submit_entry('C', 'short', 'X2MACandle sell')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_system = self.pending_entry_system
                self.active_side = self.pending_entry_side
                self.log(f'ENTRY FILLED system={self.active_system} side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
                self.pending_entry_system = None
                self.pending_entry_side = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                reverse = self.pending_reverse
                self.pending_reverse = None
                if reverse is not None and not self.position:
                    self._submit_entry(reverse[0], reverse[1], 'reverse after close')
            elif order == self.stop_order:
                self.closing_system = self.active_system
                self.closing_side = self.active_side
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
            elif order == self.limit_order:
                self.closing_system = self.active_system
                self.closing_side = self.active_side
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
                self.stop_order = None
                self.limit_order = None
                self.pending_entry_system = None
                self.pending_entry_side = None
            elif order == self.close_order:
                self.close_order = None
                self.pending_reverse = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        system = self.closing_system or self.active_system
        side = self.closing_side or self.active_side
        if system is not None and side is not None:
            key = self._mm_key(system, side)
            if trade.pnlcomm < 0:
                self.mmrec_losses[key] += 1
            else:
                self.mmrec_losses[key] = 0
        self.log(f'TRADE CLOSED system={system} side={side} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_system = None
            self.active_side = None
            self.closing_system = None
            self.closing_side = None
