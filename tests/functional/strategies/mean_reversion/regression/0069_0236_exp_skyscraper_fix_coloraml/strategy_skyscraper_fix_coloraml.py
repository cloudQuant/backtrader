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


class SkyscraperFixIndicator(bt.Indicator):
    lines = ('up_buffer', 'dn_buffer', 'buy_buffer', 'sell_buffer', 'color_state')
    params = dict(length=10, kv=0.9, percentage=0.0, use_high_low=True, atr_period=15, point_size=0.01)

    def __init__(self):
        self.addminperiod(max(self.p.length, self.p.atr_period) + 3)
        self.atr = bt.indicators.AverageTrueRange(self.data, period=self.p.atr_period)
        self.atr_high = bt.indicators.Highest(self.atr, period=self.p.length)
        self.atr_low = bt.indicators.Lowest(self.atr, period=self.p.length)
        self._prev_smin = None
        self._prev_smax = None
        self._prev_trend = 0

    @staticmethod
    def _nan():
        return float('nan')

    @staticmethod
    def _valid(value):
        return value is not None and math.isfinite(value)

    def next(self):
        up = self._nan()
        dn = self._nan()
        buy = self._nan()
        sell = self._nan()
        color = self.lines.color_state[-1] if len(self) > 1 and math.isfinite(self.lines.color_state[-1]) else 1.0
        if self._prev_smin is None:
            close = float(self.data.close[0])
            self._prev_smin = close
            self._prev_smax = close
            self._prev_trend = 0
            self.lines.up_buffer[0] = up
            self.lines.dn_buffer[0] = dn
            self.lines.buy_buffer[0] = buy
            self.lines.sell_buffer[0] = sell
            self.lines.color_state[0] = color
            return
        atrmax = float(self.atr_high[0])
        atrmin = float(self.atr_low[0])
        if not math.isfinite(atrmax) or not math.isfinite(atrmin):
            self.lines.up_buffer[0] = up
            self.lines.dn_buffer[0] = dn
            self.lines.buy_buffer[0] = buy
            self.lines.sell_buffer[0] = sell
            self.lines.color_state[0] = color
            return
        step = int(0.5 * self.p.kv * (atrmax + atrmin) / self.p.point_size)
        x2step = 2.0 * step * self.p.point_size
        close = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.p.use_high_low:
            smax0 = low + x2step
            smin0 = high - x2step
        else:
            smax0 = close + x2step
            smin0 = close - x2step
        trend0 = self._prev_trend
        if close > self._prev_smax:
            trend0 = 1
        if close < self._prev_smin:
            trend0 = -1
        if trend0 > 0:
            smin0 = max(smin0, self._prev_smin)
            up = smin0
            color = 0.0
        else:
            smax0 = min(smax0, self._prev_smax)
            dn = smax0
            color = 1.0
        prev_up = self.lines.up_buffer[-1] if len(self) > 1 else self._nan()
        prev_dn = self.lines.dn_buffer[-1] if len(self) > 1 else self._nan()
        if self._valid(prev_dn) and self._valid(up):
            buy = up
        if self._valid(prev_up) and self._valid(dn):
            sell = dn
        self.lines.up_buffer[0] = up
        self.lines.dn_buffer[0] = dn
        self.lines.buy_buffer[0] = buy
        self.lines.sell_buffer[0] = sell
        self.lines.color_state[0] = color
        self._prev_smin = smin0
        self._prev_smax = smax0
        self._prev_trend = trend0


class ColorAMLIndicator(bt.Indicator):
    lines = ('aml', 'color_state')
    params = dict(fractal=6, lag=7, shift=0, point_size=0.01)

    def __init__(self):
        self.addminperiod(2 * self.p.fractal + self.p.lag + 5)
        self._smooth_history = []
        self._prev_aml = None
        self._prev_color = 1.0

    @staticmethod
    def _window_max(line, start_ago, size):
        values = [float(line[-(start_ago + idx)]) for idx in range(size)]
        return max(values)

    @staticmethod
    def _window_min(line, start_ago, size):
        values = [float(line[-(start_ago + idx)]) for idx in range(size)]
        return min(values)

    def next(self):
        if len(self.data) < 2 * self.p.fractal + self.p.lag + 2:
            self.lines.aml[0] = float('nan')
            self.lines.color_state[0] = self._prev_color
            return
        r1 = (self._window_max(self.data.high, 0, self.p.fractal) - self._window_min(self.data.low, 0, self.p.fractal)) / float(self.p.fractal)
        r2 = (self._window_max(self.data.high, self.p.fractal, self.p.fractal) - self._window_min(self.data.low, self.p.fractal, self.p.fractal)) / float(self.p.fractal)
        r3 = (self._window_max(self.data.high, 0, 2 * self.p.fractal) - self._window_min(self.data.low, 0, 2 * self.p.fractal)) / float(2 * self.p.fractal)
        dim = 0.0
        if r1 + r2 > 0 and r3 > 0:
            dim = (math.log(r1 + r2) - math.log(r3)) * 1.44269504088896
        alpha = math.exp(-self.p.lag * (dim - 1.0))
        alpha = min(alpha, 1.0)
        alpha = max(alpha, 0.01)
        price = (float(self.data.high[0]) + float(self.data.low[0]) + 2.0 * float(self.data.open[0]) + 2.0 * float(self.data.close[0])) / 6.0
        prev_smooth = self._smooth_history[-1] if self._smooth_history else price
        smooth = alpha * price + (1.0 - alpha) * prev_smooth
        self._smooth_history.append(smooth)
        prev_aml = self._prev_aml if self._prev_aml is not None else smooth
        lag_smooth = self._smooth_history[-(self.p.lag + 1)] if len(self._smooth_history) > self.p.lag else smooth
        aml = smooth if abs(smooth - lag_smooth) >= self.p.lag * self.p.lag * self.p.point_size else prev_aml
        color = self._prev_color
        if aml > prev_aml:
            color = 2.0
        if aml < prev_aml:
            color = 0.0
        self.lines.aml[0] = aml
        self.lines.color_state[0] = color
        self._prev_aml = aml
        self._prev_color = color


class ExpSkyscraperFixColorAMLStrategy(bt.Strategy):
    params = dict(
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
        a_mm=0.1,
        a_mm_mode='LOT',
        a_stoploss_points=1000,
        a_takeprofit_points=2000,
        a_buy_pos_open=True,
        a_sell_pos_open=True,
        a_sell_pos_close=True,
        a_buy_pos_close=True,
        a_length=10,
        a_kv=0.9,
        a_percentage=0.0,
        a_use_high_low=True,
        b_mm=0.1,
        b_mm_mode='LOT',
        b_stoploss_points=1000,
        b_takeprofit_points=2000,
        b_buy_pos_open=True,
        b_sell_pos_open=True,
        b_sell_pos_close=True,
        b_buy_pos_close=True,
        b_fractal=6,
        b_lag=7,
        b_shift=0,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.a_indicator = SkyscraperFixIndicator(self.signal_data, length=self.p.a_length, kv=self.p.a_kv, percentage=self.p.a_percentage, use_high_low=self.p.a_use_high_low, point_size=self.p.point_size)
        self.b_indicator = ColorAMLIndicator(self.signal_data, fractal=self.p.b_fractal, lag=self.p.b_lag, shift=self.p.b_shift, point_size=self.p.point_size)
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.pending_entry_system = None
        self.pending_entry_side = None
        self.active_system = None
        self.active_side = None
        self.last_signal_dt = None

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

    def _size_for_entry(self, system, side):
        if system == 'A':
            mm = self.p.a_mm
            mode = self.p.a_mm_mode
            stop_points = self.p.a_stoploss_points
        else:
            mm = self.p.b_mm
            mode = self.p.b_mm_mode
            stop_points = self.p.b_stoploss_points
        if str(mode).upper() == 'LOT':
            return self._normalize_lot(mm)
        risk_cash = self.broker.getvalue() * mm
        stop_distance = stop_points * self.p.point_size
        raw = risk_cash / max(stop_distance * self.p.contract_multiplier, self.p.point_size)
        return self._normalize_lot(raw)

    def _a_signals(self):
        color_now = self.a_indicator.color_state[0]
        buy_open = self.p.a_buy_pos_open and self._has_value(self.a_indicator.buy_buffer[0])
        sell_open = self.p.a_sell_pos_open and self._has_value(self.a_indicator.sell_buffer[0])
        buy_close = self.p.a_buy_pos_close and self._has_value(color_now) and color_now == 1.0
        sell_close = self.p.a_sell_pos_close and self._has_value(color_now) and color_now == 0.0
        return {'buy_open': buy_open, 'sell_open': sell_open, 'buy_close': buy_close, 'sell_close': sell_close}

    def _b_signals(self):
        color_now = self.b_indicator.color_state[0]
        color_prev = self.b_indicator.color_state[-1] if len(self.b_indicator) > 1 else float('nan')
        buy_open = self.p.b_buy_pos_open and self._has_value(color_now) and color_now == 2.0 and (not self._has_value(color_prev) or color_prev != 2.0)
        sell_open = self.p.b_sell_pos_open and self._has_value(color_now) and color_now == 0.0 and (not self._has_value(color_prev) or color_prev != 0.0)
        buy_close = self.p.b_buy_pos_close and self._has_value(color_now) and color_now == 0.0
        sell_close = self.p.b_sell_pos_close and self._has_value(color_now) and color_now == 2.0
        return {'buy_open': buy_open, 'sell_open': sell_open, 'buy_close': buy_close, 'sell_close': sell_close}

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
            self.log(f'SKIP {system} {side} size={size}')
            return
        price = self.exec_data.close[0]
        if system == 'A':
            stop_points = self.p.a_stoploss_points
            take_points = self.p.a_takeprofit_points
        else:
            stop_points = self.p.b_stoploss_points
            take_points = self.p.b_takeprofit_points
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
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE system={self.active_system} side={self.active_side} reason={reason} reverse={reverse}')

    def next(self):
        if len(self.signal_data) < max(self.p.a_length + 3, 2 * self.p.b_fractal + self.p.b_lag + 3):
            return
        if not self._new_signal_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        a = self._a_signals()
        b = self._b_signals()
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
            return
        if a['buy_open']:
            self._submit_entry('A', 'long', 'Skyscraper_Fix buy')
        elif a['sell_open']:
            self._submit_entry('A', 'short', 'Skyscraper_Fix sell')
        elif b['buy_open']:
            self._submit_entry('B', 'long', 'ColorAML buy')
        elif b['sell_open']:
            self._submit_entry('B', 'short', 'ColorAML sell')

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
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.log(f'ENTRY FAILED status={order.getstatusname()}')
                self.entry_order = None
                self.stop_order = None
                self.limit_order = None
                self.pending_entry_system = None
                self.pending_entry_side = None
            elif order == self.close_order:
                self.log(f'CLOSE FAILED status={order.getstatusname()}')
                self.close_order = None
                self.pending_reverse = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED system={self.active_system} side={self.active_side} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_system = None
            self.active_side = None
