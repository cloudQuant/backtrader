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


class IinMASignalIndicator(bt.Indicator):
    lines = ('buy_signal', 'sell_signal')
    params = dict(fast_period=10, fast_ma='EMA', slow_period=22, slow_ma='SMA', atr_period=10)

    def __init__(self):
        ma_map = {
            'SMA': bt.indicators.SimpleMovingAverage,
            'EMA': bt.indicators.ExponentialMovingAverage,
            'SMMA': bt.indicators.SmoothedMovingAverage,
            'WMA': bt.indicators.WeightedMovingAverage,
        }
        fast_cls = ma_map.get(str(self.p.fast_ma).upper(), bt.indicators.ExponentialMovingAverage)
        slow_cls = ma_map.get(str(self.p.slow_ma).upper(), bt.indicators.SimpleMovingAverage)
        self.fast_ma = fast_cls(self.data.close, period=self.p.fast_period)
        self.slow_ma = slow_cls(self.data.close, period=self.p.slow_period)
        self._trend = 0
        self.addminperiod(max(self.p.fast_period, self.p.slow_period) + self.p.atr_period + 3)

    def next(self):
        buy_signal = 0.0
        sell_signal = 0.0
        fast_now = float(self.fast_ma[0])
        fast_prev = float(self.fast_ma[-1])
        slow_now = float(self.slow_ma[0])
        slow_prev = float(self.slow_ma[-1])
        avg_range = 0.0
        for idx in range(self.p.atr_period):
            avg_range += abs(float(self.data.high[-idx]) - float(self.data.low[-idx]))
        avg_range /= float(self.p.atr_period)
        if self._trend <= 0 and fast_now > slow_now and fast_prev < slow_prev:
            buy_signal = float(self.data.low[0]) - avg_range * 0.5
            self._trend = 1
        if self._trend >= 0 and fast_now < slow_now and fast_prev > slow_prev:
            sell_signal = float(self.data.high[0]) + avg_range * 0.5
            self._trend = -1
        self.lines.buy_signal[0] = buy_signal
        self.lines.sell_signal[0] = sell_signal


class ExpIinMASignalMMRecStrategy(bt.Strategy):
    params = dict(
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
        buy_total_mm_trigger=5,
        buy_loss_mm_trigger=3,
        sell_total_mm_trigger=5,
        sell_loss_mm_trigger=3,
        small_mm=0.01,
        mm=0.1,
        mm_mode='LOT',
        stoploss_points=1000,
        takeprofit_points=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        fast_ma_period=10,
        fast_ma_type='EMA',
        slow_ma_period=22,
        slow_ma_type='SMA',
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.indicator = IinMASignalIndicator(
            self.signal_data,
            fast_period=self.p.fast_ma_period,
            fast_ma=self.p.fast_ma_type,
            slow_period=self.p.slow_ma_period,
            slow_ma=self.p.slow_ma_type,
        )
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.pending_mm = None
        self.active_side = None
        self.closing_side = None
        self.last_signal_dt = None
        self.buy_results = deque(maxlen=max(1, int(self.p.buy_total_mm_trigger)))
        self.sell_results = deque(maxlen=max(1, int(self.p.sell_total_mm_trigger)))

    def log(self, text):
        dt = bt.num2date(self.exec_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def prenext(self):
        self.next()

    def _new_signal_bar(self):
        current = bt.num2date(self.signal_data.datetime[0])
        if self.last_signal_dt == current:
            return False
        self.last_signal_dt = current
        return True

    def _normalize_lot(self, lot):
        lot = min(max(lot, self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def _size_for_entry(self, mm):
        if str(self.p.mm_mode).upper() == 'LOT':
            return self._normalize_lot(mm)
        equity = self.broker.getvalue()
        stop_distance = self.p.stoploss_points * self.p.point_size
        raw = (equity * mm) / max(stop_distance * self.p.contract_multiplier, self.p.point_size)
        return self._normalize_lot(raw)

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _mm_for_side(self, side):
        if side == 'long':
            total_trigger = int(self.p.buy_total_mm_trigger)
            loss_trigger = int(self.p.buy_loss_mm_trigger)
            results = self.buy_results
        else:
            total_trigger = int(self.p.sell_total_mm_trigger)
            loss_trigger = int(self.p.sell_loss_mm_trigger)
            results = self.sell_results
        if total_trigger <= 0 or len(results) < total_trigger:
            return self.p.mm
        losses = sum(1 for pnl in list(results)[-total_trigger:] if pnl < 0)
        return self.p.small_mm if losses >= loss_trigger else self.p.mm

    def _signals(self):
        buy_value = float(self.indicator.buy_signal[0])
        sell_value = float(self.indicator.sell_signal[0])
        buy_open = self.p.buy_pos_open and buy_value not in (0.0,) and math.isfinite(buy_value)
        sell_open = self.p.sell_pos_open and sell_value not in (0.0,) and math.isfinite(sell_value)
        buy_close = False
        sell_close = False
        if self.position:
            for bar in range(0, 11):
                if self.position.size > 0 and self.p.buy_pos_close and len(self.indicator) > bar:
                    dn = float(self.indicator.sell_signal[-bar])
                    if dn not in (0.0,) and math.isfinite(dn):
                        buy_close = True
                        break
                if self.position.size < 0 and self.p.sell_pos_close and len(self.indicator) > bar:
                    up = float(self.indicator.buy_signal[-bar])
                    if up not in (0.0,) and math.isfinite(up):
                        sell_close = True
                        break
        return buy_open, sell_open, buy_close, sell_close

    def _submit_entry(self, side, mm, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = self._size_for_entry(mm)
        if size <= 0:
            return
        price = float(self.exec_data.close[0])
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
        self.pending_mm = mm
        self.entry_order, self.stop_order, self.limit_order = orders
        self.log(f'OPEN {side.upper()} size={size} mm={mm} reason={reason}')

    def _submit_close(self, reason, reverse=None, reverse_mm=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self.pending_mm = reverse_mm
        self.closing_side = self.active_side
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse}')

    def next(self):
        if len(self.signal_data) < max(self.p.fast_ma_period, self.p.slow_ma_period) + 15:
            return
        if not self.position and self.pending_reverse and self.entry_order is None and self.close_order is None:
            side = self.pending_reverse
            mm = self.pending_mm
            self.pending_reverse = None
            self.pending_mm = None
            self._submit_entry(side, mm, 'reverse after close')
            return
        if not self._new_signal_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        if self.position:
            if self.position.size > 0 and buy_close:
                reverse_mm = self._mm_for_side('short') if sell_open else None
                self._submit_close('sell signal seen', reverse='short' if sell_open else None, reverse_mm=reverse_mm)
            elif self.position.size < 0 and sell_close:
                reverse_mm = self._mm_for_side('long') if buy_open else None
                self._submit_close('buy signal seen', reverse='long' if buy_open else None, reverse_mm=reverse_mm)
            return
        if buy_open:
            self._submit_entry('long', self._mm_for_side('long'), 'MA crossover buy')
        elif sell_open:
            self._submit_entry('short', self._mm_for_side('short'), 'MA crossover sell')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                reverse = self.pending_reverse
                mm = self.pending_mm
                self.pending_reverse = None
                self.pending_mm = None
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, mm, 'reverse after close')
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                self.pending_reverse = None
                self.pending_mm = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        pnl = trade.pnlcomm
        direction = self.closing_side or self.active_side or ('long' if trade.long else 'short')
        if direction == 'long':
            self.buy_results.append(pnl)
        else:
            self.sell_results.append(pnl)
        self.log(f'TRADE CLOSED side={direction} pnl={pnl:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.closing_side = None
