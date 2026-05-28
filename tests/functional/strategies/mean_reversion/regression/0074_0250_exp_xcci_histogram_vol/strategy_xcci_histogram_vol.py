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


class XCCIHistogramVolIndicator(bt.Indicator):
    lines = ('color_state', 'value', 'max_level', 'up_level', 'dn_level', 'min_level')
    params = dict(cci_period=14, high_level2=100, high_level1=80, low_level1=-80, low_level2=-100, ma_length=12)

    def __init__(self):
        self._scaled_history = []
        self._volume_history = []
        self.addminperiod(max(self.p.cci_period, self.p.ma_length) + 3)

    def next(self):
        vol = float(self.data.volume[0]) if len(self.data.volume) else 0.0
        typical_prices = []
        for idx in range(self.p.cci_period):
            typical_prices.append((float(self.data.high[-idx]) + float(self.data.low[-idx]) + float(self.data.close[-idx])) / 3.0)
        tp_now = typical_prices[0]
        tp_sma = sum(typical_prices) / float(len(typical_prices))
        mean_dev = sum(abs(tp - tp_sma) for tp in typical_prices) / float(len(typical_prices))
        if mean_dev <= 1e-12:
            cci_value = 0.0
        else:
            cci_value = (tp_now - tp_sma) / (0.015 * mean_dev)
        raw = cci_value * vol
        self._scaled_history.append(raw)
        self._volume_history.append(vol)
        if len(self._scaled_history) > self.p.ma_length:
            self._scaled_history.pop(0)
        if len(self._volume_history) > self.p.ma_length:
            self._volume_history.pop(0)
        scaled = sum(self._scaled_history) / float(len(self._scaled_history))
        avg_vol = sum(self._volume_history) / float(len(self._volume_history)) if self._volume_history else max(vol, 1.0)
        max_level = self.p.high_level2 * avg_vol
        up_level = self.p.high_level1 * avg_vol
        dn_level = self.p.low_level1 * avg_vol
        min_level = self.p.low_level2 * avg_vol
        clr = 2.0
        if scaled > max_level:
            clr = 0.0
        elif scaled > up_level:
            clr = 1.0
        elif scaled < min_level:
            clr = 4.0
        elif scaled < dn_level:
            clr = 3.0
        self.lines.value[0] = scaled
        self.lines.max_level[0] = max_level
        self.lines.up_level[0] = up_level
        self.lines.dn_level[0] = dn_level
        self.lines.min_level[0] = min_level
        self.lines.color_state[0] = clr


class ExpXCCIHistogramVolStrategy(bt.Strategy):
    params = dict(
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
        mm1=0.1,
        mm2=0.2,
        mm_mode='LOT',
        stoploss_points=1000,
        takeprofit_points=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        cci_period=14,
        high_level2=100,
        high_level1=80,
        low_level1=-80,
        low_level2=-100,
        ma_length=12,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.indicator = XCCIHistogramVolIndicator(
            self.signal_data,
            cci_period=self.p.cci_period,
            high_level2=self.p.high_level2,
            high_level1=self.p.high_level1,
            low_level1=self.p.low_level1,
            low_level2=self.p.low_level2,
            ma_length=self.p.ma_length,
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

    def _signal_state(self):
        prev_color = float(self.indicator.color_state[-1])
        curr_color = float(self.indicator.color_state[0])
        if not math.isfinite(prev_color) or not math.isfinite(curr_color):
            return None
        if prev_color == 1.0 and curr_color > 1.0:
            return ('buy', self.p.mm1)
        if prev_color == 0.0 and curr_color > 0.0:
            return ('buy', self.p.mm2)
        if prev_color == 3.0 and curr_color < 3.0:
            return ('sell', self.p.mm1)
        if prev_color == 4.0 and curr_color < 4.0:
            return ('sell', self.p.mm2)
        return None

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
        if len(self.signal_data) < max(self.p.cci_period, self.p.ma_length) + 5:
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
        state = self._signal_state()
        if state is None:
            return
        side, mm = state
        if side == 'buy':
            if self.position.size < 0 and self.p.buy_pos_close:
                self._submit_close('buy signal', reverse='long' if self.p.buy_pos_open else None, reverse_mm=mm)
                return
            if not self.position and self.p.buy_pos_open:
                self._submit_entry('long', mm, 'xcci buy transition')
        elif side == 'sell':
            if self.position.size > 0 and self.p.sell_pos_close:
                self._submit_close('sell signal', reverse='short' if self.p.sell_pos_open else None, reverse_mm=mm)
                return
            if not self.position and self.p.sell_pos_open:
                self._submit_entry('short', mm, 'xcci sell transition')

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
        self.log(f'TRADE CLOSED side={self.closing_side or self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.closing_side = None
