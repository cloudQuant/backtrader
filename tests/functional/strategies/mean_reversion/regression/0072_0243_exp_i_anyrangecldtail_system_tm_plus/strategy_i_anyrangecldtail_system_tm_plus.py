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


class AnyRangeCldTailIndicator(bt.Indicator):
    lines = ('color_state', 'upper', 'lower')
    params = dict(time1='02:00', time2='07:00')

    def __init__(self):
        self._time1 = self._parse_hhmm(self.p.time1)
        self._time2 = self._parse_hhmm(self.p.time2)
        self._window_start = min(self._time1, self._time2)
        self._window_end = max(self._time1, self._time2)
        self._current_day = None
        self._range_high = None
        self._range_low = None
        self._channel_high = None
        self._channel_low = None
        self._window_finalized = False
        self.addminperiod(2)

    @staticmethod
    def _parse_hhmm(value):
        hour, minute = value.split(':')
        return int(hour) * 60 + int(minute)

    def next(self):
        dt = bt.num2date(self.data.datetime[0])
        day = dt.date()
        minute = dt.hour * 60 + dt.minute
        if self._current_day != day:
            self._current_day = day
            self._range_high = None
            self._range_low = None
            self._channel_high = None
            self._channel_low = None
            self._window_finalized = False
        in_window = self._window_start < minute <= self._window_end
        if in_window:
            high = float(self.data.high[0])
            low = float(self.data.low[0])
            self._range_high = high if self._range_high is None else max(self._range_high, high)
            self._range_low = low if self._range_low is None else min(self._range_low, low)
        elif minute > self._window_end and not self._window_finalized and self._range_high is not None and self._range_low is not None:
            self._channel_high = self._range_high
            self._channel_low = self._range_low
            self._window_finalized = True
        color = 4.0
        if self._channel_high is not None and self._channel_low is not None and not in_window:
            close = float(self.data.close[0])
            open_ = float(self.data.open[0])
            if close > self._channel_high:
                color = 3.0 if close >= open_ else 2.0
            elif close < self._channel_low:
                color = 0.0 if close <= open_ else 1.0
        self.lines.color_state[0] = color
        self.lines.upper[0] = self._channel_high if self._channel_high is not None else float('nan')
        self.lines.lower[0] = self._channel_low if self._channel_low is not None else float('nan')


class ExpAnyRangeCldTailSystemTmPlusStrategy(bt.Strategy):
    params = dict(
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
        mm=0.1,
        mm_mode='LOT',
        stoploss_points=1000,
        takeprofit_points=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        time_trade=True,
        hold_minutes=1500,
        time1='02:00',
        time2='07:00',
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.indicator = AnyRangeCldTailIndicator(self.signal_data, time1=self.p.time1, time2=self.p.time2)
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.active_side = None
        self.closing_side = None
        self.last_signal_dt = None
        self.entry_dt = None

    def log(self, text):
        dt = bt.num2date(self.exec_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def prenext(self):
        self.next()

    @staticmethod
    def _has_value(value):
        return value is not None and math.isfinite(value)

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

    def _size_for_entry(self):
        if str(self.p.mm_mode).upper() == 'LOT':
            return self._normalize_lot(self.p.mm)
        equity = self.broker.getvalue()
        stop_distance = self.p.stoploss_points * self.p.point_size
        raw = (equity * self.p.mm) / max(stop_distance * self.p.contract_multiplier, self.p.point_size)
        return self._normalize_lot(raw)

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _signals(self):
        color_now = self.indicator.color_state[0]
        color_prev = self.indicator.color_state[-1] if len(self.indicator) > 1 else float('nan')
        if not self._has_value(color_now) or not self._has_value(color_prev):
            return False, False, False, False
        bullish_now = color_now in (2.0, 3.0)
        bearish_now = color_now in (0.0, 1.0)
        bullish_prev = color_prev in (2.0, 3.0)
        bearish_prev = color_prev in (0.0, 1.0)
        buy_open = self.p.buy_pos_open and bullish_now and not bullish_prev
        sell_open = self.p.sell_pos_open and bearish_now and not bearish_prev
        buy_close = self.p.buy_pos_close and bearish_now
        sell_close = self.p.sell_pos_close and bullish_now
        return buy_open, sell_open, buy_close, sell_close

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = self._size_for_entry()
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
        self.entry_order, self.stop_order, self.limit_order = orders
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self.closing_side = self.active_side
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse}')

    def _check_time_close(self):
        if not self.position or not self.p.time_trade or self.entry_dt is None:
            return False
        current = bt.num2date(self.exec_data.datetime[0])
        held_minutes = (current - self.entry_dt).total_seconds() / 60.0
        if held_minutes >= self.p.hold_minutes:
            self._submit_close('time expiry')
            return True
        return False

    def next(self):
        if len(self.signal_data) < 3:
            return
        if self._check_time_close():
            return
        if not self.position and self.pending_reverse and self.entry_order is None and self.close_order is None:
            side = self.pending_reverse
            self.pending_reverse = None
            self._submit_entry(side, 'reverse after close')
            return
        if not self._new_signal_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        if self.position:
            if self.position.size > 0 and buy_close:
                self._submit_close('signal sell', reverse='short' if sell_open else None)
            elif self.position.size < 0 and sell_close:
                self._submit_close('signal buy', reverse='long' if buy_open else None)
            return
        if buy_open:
            self._submit_entry('long', 'channel breakout buy')
        elif sell_open:
            self._submit_entry('short', 'channel breakout sell')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_dt = bt.num2date(self.exec_data.datetime[0])
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                self.entry_dt = None
                reverse = self.pending_reverse
                self.pending_reverse = None
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, 'reverse after close')
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.entry_dt = None
                self.active_side = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.entry_dt = None
                self.active_side = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
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
        self.log(f'TRADE CLOSED side={self.closing_side or self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.closing_side = None
            self.entry_dt = None
