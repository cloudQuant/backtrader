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


class XDeMarkerHistogramVolDirectIndicator(bt.Indicator):
    lines = ('value', 'color_zone', 'color_direct', 'upper2', 'upper1', 'lower1', 'lower2')
    params = dict(
        de_marker_period=14,
        volume_type='tick',
        high_level2=20,
        high_level1=15,
        low_level1=-15,
        low_level2=-20,
        ma_method='MODE_SMA_',
        ma_length=12,
        ma_phase=15,
    )

    def __init__(self):
        self._demax = deque(maxlen=max(1, int(self.p.de_marker_period)))
        self._demin = deque(maxlen=max(1, int(self.p.de_marker_period)))
        self._raw = deque(maxlen=max(1, int(self.p.ma_length)))
        self._vol = deque(maxlen=max(1, int(self.p.ma_length)))
        self.addminperiod(max(int(self.p.de_marker_period), int(self.p.ma_length)) + 2)

    @staticmethod
    def _nan():
        return float('nan')

    @staticmethod
    def _finite(value):
        return value is not None and math.isfinite(value)

    def _bar_volume(self):
        volume_type = str(self.p.volume_type).lower()
        if volume_type in {'real', 'volume_real', 'volume'}:
            raw = float(self.data.openinterest[0])
            if math.isfinite(raw) and raw > 0:
                return raw
        raw = float(self.data.volume[0])
        return raw if math.isfinite(raw) else 0.0

    def next(self):
        if len(self.data) < 2:
            for line in self.lines:
                line[0] = self._nan()
            return

        high_now = float(self.data.high[0])
        high_prev = float(self.data.high[-1])
        low_now = float(self.data.low[0])
        low_prev = float(self.data.low[-1])
        vol_now = self._bar_volume()

        self._demax.append(max(high_now - high_prev, 0.0))
        self._demin.append(max(low_prev - low_now, 0.0))

        value = self._nan()
        color_zone = self._nan()
        color_direct = self.lines.color_direct[-1] if len(self) > 1 and self._finite(self.lines.color_direct[-1]) else self._nan()
        upper2 = self._nan()
        upper1 = self._nan()
        lower1 = self._nan()
        lower2 = self._nan()

        if len(self._demax) >= int(self.p.de_marker_period) and len(self._demin) >= int(self.p.de_marker_period):
            sum_max = sum(self._demax)
            sum_min = sum(self._demin)
            denom = sum_max + sum_min
            demarker = (sum_max / denom) if denom > 0 else 0.5
            raw = ((demarker * 100.0) - 50.0) * vol_now
            self._raw.append(raw)
            self._vol.append(vol_now)

            if len(self._raw) >= int(self.p.ma_length) and len(self._vol) >= int(self.p.ma_length):
                if str(self.p.ma_method).upper() != 'MODE_SMA_':
                    raise ValueError('Current backtrader migration only supports MODE_SMA_ for XDeMarker_Histogram_Vol_Direct')
                value = sum(self._raw) / len(self._raw)
                avg_vol = sum(self._vol) / len(self._vol)
                upper2 = self.p.high_level2 * avg_vol
                upper1 = self.p.high_level1 * avg_vol
                lower1 = self.p.low_level1 * avg_vol
                lower2 = self.p.low_level2 * avg_vol
                if value > upper2:
                    color_zone = 0.0
                elif value > upper1:
                    color_zone = 1.0
                elif value < lower2:
                    color_zone = 4.0
                elif value < lower1:
                    color_zone = 3.0
                else:
                    color_zone = 2.0

                prev_value = self.lines.value[-1] if len(self) > 1 and self._finite(self.lines.value[-1]) else self._nan()
                prev_direct = self.lines.color_direct[-1] if len(self) > 1 and self._finite(self.lines.color_direct[-1]) else 1.0
                if not self._finite(prev_value):
                    color_direct = prev_direct
                elif value > prev_value:
                    color_direct = 0.0
                elif value < prev_value:
                    color_direct = 1.0
                else:
                    color_direct = prev_direct

        self.lines.value[0] = value
        self.lines.color_zone[0] = color_zone
        self.lines.color_direct[0] = color_direct
        self.lines.upper2[0] = upper2
        self.lines.upper1[0] = upper1
        self.lines.lower1[0] = lower1
        self.lines.lower2[0] = lower2


class ExpXDeMarkerHistogramVolDirectStrategy(bt.Strategy):
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
        sell_pos_close=True,
        buy_pos_close=True,
        de_marker_period=14,
        volume_type='tick',
        high_level2=20,
        high_level1=15,
        low_level1=-15,
        low_level2=-20,
        ma_method='MODE_SMA_',
        ma_length=12,
        ma_phase=15,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.indicator = XDeMarkerHistogramVolDirectIndicator(
            self.signal_data,
            de_marker_period=self.p.de_marker_period,
            volume_type=self.p.volume_type,
            high_level2=self.p.high_level2,
            high_level1=self.p.high_level1,
            low_level1=self.p.low_level1,
            low_level2=self.p.low_level2,
            ma_method=self.p.ma_method,
            ma_length=self.p.ma_length,
            ma_phase=self.p.ma_phase,
        )
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.last_signal_dt = None
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.exec_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    @staticmethod
    def _finite(value):
        return value is not None and math.isfinite(value)

    def _new_signal_bar(self):
        current = bt.num2date(self.signal_data.datetime[0])
        if self.last_signal_dt == current:
            return False
        self.last_signal_dt = current
        return True

    def _normalize_lot(self, lot):
        lot = min(max(float(lot), self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def _position_size(self):
        if str(self.p.mm_mode).upper() == 'LOT':
            return self._normalize_lot(self.p.mm)
        risk_cash = self.broker.getvalue() * (self.p.mm / 100.0)
        stop_distance = self.p.stoploss_points * self.p.point_size
        raw = risk_cash / max(stop_distance * self.p.contract_multiplier, self.p.point_size)
        return self._normalize_lot(raw)

    def _signal_flags(self):
        color_now = self.indicator.color_direct[0]
        color_prev = self.indicator.color_direct[-1] if len(self.indicator) > 1 else float('nan')
        buy_open = self.p.buy_pos_open and self._finite(color_now) and self._finite(color_prev) and color_now == 0.0 and color_prev == 1.0
        sell_open = self.p.sell_pos_open and self._finite(color_now) and self._finite(color_prev) and color_now == 1.0 and color_prev == 0.0
        buy_close = self.p.buy_pos_close and self._finite(color_now) and color_now == 1.0
        sell_close = self.p.sell_pos_close and self._finite(color_now) and color_now == 0.0
        return buy_open, sell_open, buy_close, sell_close

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = self._position_size()
        if size <= 0:
            self.log(f'SKIP {side.upper()} size={size}')
            return
        price = self.exec_data.close[0]
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

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE size={self.position.size} reason={reason}')

    def next(self):
        min_bars = max(int(self.p.de_marker_period), int(self.p.ma_length)) + 5
        if len(self.signal_data) < min_bars:
            return

        if not self.position and self.pending_reverse and self.entry_order is None and self.close_order is None:
            side = self.pending_reverse
            self.pending_reverse = None
            self._submit_entry(side, 'pending reverse signal')
            return

        if not self._new_signal_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return

        buy_open, sell_open, buy_close, sell_close = self._signal_flags()

        if self.position:
            if self.position.size > 0 and buy_close:
                self.pending_reverse = 'short' if sell_open else None
                self._submit_close('direction turned down')
            elif self.position.size < 0 and sell_close:
                self.pending_reverse = 'long' if buy_open else None
                self._submit_close('direction turned up')
            return

        if buy_open:
            self._submit_entry('long', 'rising direct color')
        elif sell_open:
            self._submit_entry('short', 'falling direct color')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.log(f'ENTRY FILLED side={"BUY" if order.isbuy() else "SELL"} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
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
            elif order == self.close_order:
                self.log(f'CLOSE FAILED status={order.getstatusname()}')
                self.close_order = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        side = 'long' if trade.long else 'short'
        self.log(f'TRADE CLOSED side={side} pnl={trade.pnl:.2f} net={trade.pnlcomm:.2f}')
