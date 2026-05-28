from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class TimeZonePivotsFeed(btfeeds.PandasData):
    lines = ('upper', 'lower', 'color_idx')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6), ('upper', 7), ('lower', 8), ('color_idx', 9),
    )


def build_resampled_frame(df, indicator_minutes):
    rule = f'{int(indicator_minutes)}min'
    signal_df = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
        'spread': 'last',
    })
    signal_df = signal_df.dropna(subset=['open', 'high', 'low', 'close']).copy()
    signal_df['openinterest'] = signal_df['openinterest'].fillna(0)
    signal_df['spread'] = signal_df['spread'].fillna(0)
    return signal_df


def build_timezone_pivots_frame(df, indicator_minutes, start_hour, offset_points, point_size):
    signal_df = build_resampled_frame(df, indicator_minutes)
    upper = []
    lower = []
    color_idx = []
    last_open = None
    last_day = None
    distance = float(offset_points) * float(point_size)

    for dt, row in signal_df.iterrows():
        if last_day != dt.day and int(dt.hour) == int(start_hour):
            last_day = dt.day
            last_open = float(row['open'])
        if last_open is None:
            upper.append(math.nan)
            lower.append(math.nan)
            color_idx.append(2.0)
            continue
        up = last_open + distance
        dn = last_open - distance
        upper.append(up)
        lower.append(dn)
        color = 2.0
        if float(row['close']) > up:
            color = 0.0 if float(row['close']) >= float(row['open']) else 1.0
        elif float(row['close']) < dn:
            color = 4.0 if float(row['close']) <= float(row['open']) else 3.0
        color_idx.append(color)

    signal_df = signal_df.copy()
    signal_df['upper'] = upper
    signal_df['lower'] = lower
    signal_df['color_idx'] = color_idx
    return signal_df


class ExpTimeZonePivotsOpenSystemTmPlusStrategy(bt.Strategy):
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
        hold_minutes=720,
        signal_bar=1,
        start_hour=0,
        offset_points=200,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1]
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.active_side = None
        self.closing_side = None
        self.entry_datetime = None
        self.last_signal_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.exec_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        lot = min(max(float(lot), self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def _size_for_entry(self):
        if str(self.p.mm_mode).upper() == 'LOT':
            return self._normalize_lot(self.p.mm)
        equity = self.broker.getvalue()
        stop_distance = self.p.stoploss_points * self.p.point_size
        raw = (equity * float(self.p.mm)) / max(stop_distance * self.p.contract_multiplier, self.p.point_size)
        return self._normalize_lot(raw)

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

    def _current_signal_dt(self):
        recent_ago = max(int(self.p.signal_bar), 1) - 1
        return bt.num2date(self.signal_data.datetime[-recent_ago]) if recent_ago else bt.num2date(self.signal_data.datetime[0])

    def _new_signal_bar(self):
        current = self._current_signal_dt()
        if self.last_signal_dt == current:
            return False
        self.last_signal_dt = current
        return True

    def _check_time_exit(self):
        if not self.position or not self.p.time_trade or self.entry_datetime is None:
            return False
        current_dt = bt.num2date(self.exec_data.datetime[0])
        if (current_dt - self.entry_datetime).total_seconds() >= self.p.hold_minutes * 60:
            self._submit_close('time based exit')
            return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.signal_data) < max(int(self.p.signal_bar), 1) + 1:
            return
        if self.entry_order is None and self.close_order is None and self._check_time_exit():
            return
        if not self._new_signal_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return

        recent_ago = max(int(self.p.signal_bar), 1) - 1
        prev_ago = max(int(self.p.signal_bar), 1)
        color_now = float(self.signal_data.color_idx[-recent_ago]) if recent_ago else float(self.signal_data.color_idx[0])
        color_prev = float(self.signal_data.color_idx[-prev_ago])
        buy_open = self.p.buy_pos_open and color_prev > 1.0 and color_now < 2.0
        sell_open = self.p.sell_pos_open and color_prev < 3.0 and color_now > 2.0

        if self.position.size > 0 and sell_open and self.p.buy_pos_close:
            self._submit_close('pivot channel down breakout', reverse='short' if self.p.sell_pos_open else None)
            return
        if self.position.size < 0 and buy_open and self.p.sell_pos_close:
            self._submit_close('pivot channel up breakout', reverse='long' if self.p.buy_pos_open else None)
            return
        if self.position:
            return
        if buy_open:
            self._submit_entry('long', 'pivot bullish breakout')
        elif sell_open:
            self._submit_entry('short', 'pivot bearish breakout')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_datetime = bt.num2date(self.exec_data.datetime[0])
                if order.executed.size > 0:
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                reverse = self.pending_reverse
                self.pending_reverse = None
                self.active_side = None
                self.entry_datetime = None
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, 'reverse after close')
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.entry_datetime = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
                self.entry_datetime = None
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
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED side={self.closing_side or self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        self.closing_side = None
        if not self.position:
            self.active_side = None
            self.entry_datetime = None
