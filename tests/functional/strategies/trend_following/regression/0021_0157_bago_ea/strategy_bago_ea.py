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


def resample_ohlcv(df, minutes):
    rule = f'{int(minutes)}min'
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
        'spread': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close']).copy()
    out['openinterest'] = out['openinterest'].fillna(0)
    out['spread'] = out['spread'].fillna(0)
    return out


def build_signal_frame(df, execution_minutes, ema_fast_period, ema_slow_period, rsi_period, cross_effective_time, tunnel_bandwidth, tunnel_safe_zone, london_open, newyork_open, tokyo_open):
    frame = resample_ohlcv(df, execution_minutes)
    frame['ema_fast'] = frame['close'].ewm(span=ema_fast_period, adjust=False).mean()
    frame['ema_slow'] = frame['close'].ewm(span=ema_slow_period, adjust=False).mean()
    frame['vegas_fast'] = frame['close'].ewm(span=144, adjust=False).mean()
    frame['vegas_slow'] = frame['close'].ewm(span=169, adjust=False).mean()
    frame['rsi'] = bt.indicators.RSI_Safe if False else None
    delta = frame['close'].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / rsi_period, adjust=False, min_periods=rsi_period).mean()
    avg_loss = loss.ewm(alpha=1.0 / rsi_period, adjust=False, min_periods=rsi_period).mean()
    rs = avg_gain / avg_loss.replace(0.0, math.nan)
    frame['rsi'] = 100.0 - (100.0 / (1.0 + rs))
    frame = frame.dropna(subset=['ema_fast', 'ema_slow', 'vegas_fast', 'vegas_slow', 'rsi']).copy()

    long_entry = []
    short_entry = []
    long_exit = []
    short_exit = []
    tunnel_up_values = []
    tunnel_down_values = []

    ema_up_counter = 0
    ema_down_counter = 0
    rsi_up_counter = 0
    rsi_down_counter = 0
    tunnel_up = False
    tunnel_down = False

    for idx in range(len(frame)):
        if idx < 2:
            long_entry.append(False)
            short_entry.append(False)
            long_exit.append(False)
            short_exit.append(False)
            tunnel_up_values.append(False)
            tunnel_down_values.append(False)
            continue

        current = frame.iloc[idx]
        prev = frame.iloc[idx - 1]
        prev2 = frame.iloc[idx - 2]
        hour = frame.index[idx].hour
        session_allowed = (
            (london_open and 7 <= hour <= 16)
            or (newyork_open and 12 <= hour <= 21)
            or (tokyo_open and 0 <= hour <= 8)
            or hour >= 23
        )

        if prev['rsi'] > 50 and prev2['rsi'] < 50:
            rsi_up_counter = cross_effective_time
        if prev['rsi'] < 50 and prev2['rsi'] > 50:
            rsi_down_counter = cross_effective_time
        if prev['ema_fast'] > prev['ema_slow'] and prev2['ema_fast'] < prev2['ema_slow']:
            ema_up_counter = cross_effective_time
        if prev['ema_fast'] < prev['ema_slow'] and prev2['ema_fast'] > prev2['ema_slow']:
            ema_down_counter = cross_effective_time

        if prev['close'] > current['vegas_fast'] and prev['close'] > current['vegas_slow'] and (prev2['close'] < current['vegas_fast'] or prev2['close'] < current['vegas_slow']):
            tunnel_up = True
            tunnel_down = False
        if prev['close'] < current['vegas_fast'] and prev['close'] < current['vegas_slow'] and (prev2['close'] > current['vegas_fast'] or prev2['close'] > current['vegas_slow']):
            tunnel_up = False
            tunnel_down = True

        ema_up_valid = ema_up_counter > 0
        ema_down_valid = ema_down_counter > 0
        rsi_up_valid = rsi_up_counter > 0
        rsi_down_valid = rsi_down_counter > 0

        long_filter = (
            (prev['close'] >= current['vegas_slow'] + tunnel_bandwidth and prev['close'] <= current['vegas_slow'] + tunnel_safe_zone and prev['open'] < prev['close'])
            or (prev['close'] <= current['vegas_slow'] - tunnel_bandwidth)
        )
        short_filter = (
            (prev['close'] <= current['vegas_slow'] - tunnel_bandwidth and prev['close'] >= current['vegas_slow'] - tunnel_safe_zone and prev['open'] > prev['close'])
            or (prev['close'] >= current['vegas_slow'] + tunnel_bandwidth)
        )

        long_entry.append(bool(session_allowed and ema_up_valid and rsi_up_valid and long_filter))
        short_entry.append(bool(session_allowed and ema_down_valid and rsi_down_valid and short_filter))
        long_exit.append(bool(ema_down_valid or rsi_down_valid))
        short_exit.append(bool(ema_up_valid or rsi_up_valid))
        tunnel_up_values.append(tunnel_up)
        tunnel_down_values.append(tunnel_down)

        ema_up_counter = max(0, ema_up_counter - 1)
        ema_down_counter = max(0, ema_down_counter - 1)
        rsi_up_counter = max(0, rsi_up_counter - 1)
        rsi_down_counter = max(0, rsi_down_counter - 1)

    frame['long_entry'] = long_entry
    frame['short_entry'] = short_entry
    frame['long_exit'] = long_exit
    frame['short_exit'] = short_exit
    frame['tunnel_up'] = tunnel_up_values
    frame['tunnel_down'] = tunnel_down_values
    return frame[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread', 'vegas_slow', 'tunnel_up', 'tunnel_down', 'long_entry', 'short_entry', 'long_exit', 'short_exit']].dropna()


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread', 'vegas_slow', 'tunnel_up', 'tunnel_down', 'long_entry', 'short_entry', 'long_exit', 'short_exit')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6), ('vegas_slow', 7), ('tunnel_up', 8), ('tunnel_down', 9),
        ('long_entry', 10), ('short_entry', 11), ('long_exit', 12), ('short_exit', 13),
    )


class BagoEaStrategy(bt.Strategy):
    params = dict(
        fixed_lot=3.0,
        point_size=0.0001,
        stoploss_pips=30,
        stoploss_to_fibo_pips=20,
        trailing_stop_pips=30,
        trailing_step1_pips=55,
        trailing_step2_pips=89,
        trailing_step3_pips=144,
        lots_close_partial1=1.0,
        lots_close_partial2=1.0,
        tunnel_bandwidth_pips=5,
        tunnel_safe_zone_pips=120,
        cross_effective_time=2,
        london_open=True,
        newyork_open=True,
        tokyo_open=False,
        ema_fast_period=5,
        ema_slow_period=12,
        rsi_period=21,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.entry_order = None
        self.close_order = None
        self.partial_order_1 = None
        self.partial_order_2 = None
        self.stop_order = None
        self.active_side = None
        self.active_stop_price = None
        self.pending_reverse = None
        self.part1_done = False
        self.part2_done = False
        self.last_bar_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_bar(self):
        current = bt.num2date(self.data0_feed.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _cancel_stop(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None

    def _place_stop(self, stop_price):
        if not self.position:
            return
        size = abs(self.position.size)
        if size <= 0:
            return
        self._cancel_stop()
        if self.position.size > 0:
            self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=stop_price)
        else:
            self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=stop_price)
        self.active_stop_price = stop_price

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.entry_order = self.buy(size=size) if side == 'long' else self.sell(size=size)
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None, size=None):
        if not self.position:
            return
        if size is None and self.close_order is not None:
            return
        if size is None:
            self.pending_reverse = reverse
            self._cancel_stop()
            self.close_order = self.close()
        else:
            close_size = min(abs(self.position.size), float(size))
            if close_size <= 0:
                return
            self._cancel_stop()
            if self.position.size > 0:
                if size == self.p.lots_close_partial1:
                    self.partial_order_1 = self.sell(size=close_size)
                else:
                    self.partial_order_2 = self.sell(size=close_size)
            else:
                if size == self.p.lots_close_partial1:
                    self.partial_order_1 = self.buy(size=close_size)
                else:
                    self.partial_order_2 = self.buy(size=close_size)
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse} size={size}')

    def _manage_long(self):
        close_price = float(self.data0_feed.close[0])
        vegas_slow = float(self.data0_feed.vegas_slow[0])
        tunnel_up = bool(self.data0_feed.tunnel_up[0])
        band = self.p.tunnel_bandwidth_pips * self.p.point_size
        fibo_stop = self.p.stoploss_to_fibo_pips * self.p.point_size
        trail = self.p.trailing_stop_pips * self.p.point_size
        step1 = self.p.trailing_step1_pips * self.p.point_size
        step2 = self.p.trailing_step2_pips * self.p.point_size
        step3 = self.p.trailing_step3_pips * self.p.point_size

        if bool(self.data0_feed.long_exit[0]):
            self._submit_close('ema/rsi reversed', reverse='short' if bool(self.data0_feed.short_entry[0]) else None)
            return

        candidate = self.active_stop_price if self.active_stop_price is not None else self.position.price - self.p.stoploss_pips * self.p.point_size
        if tunnel_up:
            if close_price >= vegas_slow + step3:
                candidate = max(candidate, close_price - trail)
            elif close_price >= vegas_slow + step2:
                if not self.part2_done and abs(self.position.size) > self.p.lots_close_partial2:
                    self.part2_done = True
                    self._submit_close('partial 2', size=self.p.lots_close_partial2)
                    return
                candidate = max(candidate, close_price - trail)
            elif close_price >= vegas_slow + step1:
                if not self.part1_done and abs(self.position.size) > self.p.lots_close_partial1:
                    self.part1_done = True
                    self._submit_close('partial 1', size=self.p.lots_close_partial1)
                    return
                candidate = max(candidate, close_price - trail)
            else:
                candidate = max(candidate, vegas_slow - (band + fibo_stop))
        else:
            if close_price >= vegas_slow - step1:
                candidate = max(candidate, vegas_slow - (step1 + fibo_stop))

        if self.active_stop_price is None or candidate > self.active_stop_price + self.p.point_size:
            self._place_stop(candidate)

    def _manage_short(self):
        close_price = float(self.data0_feed.close[0])
        vegas_slow = float(self.data0_feed.vegas_slow[0])
        tunnel_down = bool(self.data0_feed.tunnel_down[0])
        band = self.p.tunnel_bandwidth_pips * self.p.point_size
        fibo_stop = self.p.stoploss_to_fibo_pips * self.p.point_size
        trail = self.p.trailing_stop_pips * self.p.point_size
        step1 = self.p.trailing_step1_pips * self.p.point_size
        step2 = self.p.trailing_step2_pips * self.p.point_size
        step3 = self.p.trailing_step3_pips * self.p.point_size

        if bool(self.data0_feed.short_exit[0]):
            self._submit_close('ema/rsi reversed', reverse='long' if bool(self.data0_feed.long_entry[0]) else None)
            return

        candidate = self.active_stop_price if self.active_stop_price is not None else self.position.price + self.p.stoploss_pips * self.p.point_size
        if tunnel_down:
            if close_price <= vegas_slow - step3:
                candidate = min(candidate, close_price + trail)
            elif close_price <= vegas_slow - step2:
                if not self.part2_done and abs(self.position.size) > self.p.lots_close_partial2:
                    self.part2_done = True
                    self._submit_close('partial 2', size=self.p.lots_close_partial2)
                    return
                candidate = min(candidate, close_price + trail)
            elif close_price <= vegas_slow - step1:
                if not self.part1_done and abs(self.position.size) > self.p.lots_close_partial1:
                    self.part1_done = True
                    self._submit_close('partial 1', size=self.p.lots_close_partial1)
                    return
                candidate = min(candidate, close_price + trail)
            else:
                candidate = min(candidate, vegas_slow + (band + fibo_stop))
        else:
            if close_price <= vegas_slow + step1:
                candidate = min(candidate, vegas_slow + (step1 + fibo_stop))

        if self.active_stop_price is None or candidate < self.active_stop_price - self.p.point_size:
            self._place_stop(candidate)

    def next(self):
        self.bar_num += 1
        if len(self.data0_feed) < 20:
            return
        if not self._new_bar():
            return
        if self.entry_order is not None or self.close_order is not None or self.partial_order_1 is not None or self.partial_order_2 is not None:
            return
        if self.position.size > 0:
            self._manage_long()
            return
        if self.position.size < 0:
            self._manage_short()
            return
        if bool(self.data0_feed.long_entry[0]):
            self._submit_entry('long', 'ema+rsi cross with vegas filter')
        elif bool(self.data0_feed.short_entry[0]):
            self._submit_entry('short', 'ema+rsi cross with vegas filter')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.part1_done = False
                self.part2_done = False
                if order.executed.size > 0:
                    self.buy_count += 1
                    stop_price = order.executed.price - self.p.stoploss_pips * self.p.point_size
                else:
                    self.sell_count += 1
                    stop_price = order.executed.price + self.p.stoploss_pips * self.p.point_size
                self.entry_order = None
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self._place_stop(stop_price)
            elif order == self.close_order:
                self.close_order = None
                self.stop_order = None
                self.active_stop_price = None
                self.active_side = None
                reverse = self.pending_reverse
                self.pending_reverse = None
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, 'reverse after close')
            elif order == self.partial_order_1:
                self.partial_order_1 = None
                self.log(f'PARTIAL1 FILLED price={order.executed.price:.5f} size={order.executed.size}')
                if self.position:
                    self._place_stop(self.active_stop_price if self.active_stop_price is not None else self.position.price)
            elif order == self.partial_order_2:
                self.partial_order_2 = None
                self.log(f'PARTIAL2 FILLED price={order.executed.price:.5f} size={order.executed.size}')
                if self.position:
                    self._place_stop(self.active_stop_price if self.active_stop_price is not None else self.position.price)
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.active_stop_price = None
                self.active_side = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                self.pending_reverse = None
            elif order == self.partial_order_1:
                self.partial_order_1 = None
            elif order == self.partial_order_2:
                self.partial_order_2 = None
            elif order == self.stop_order:
                self.stop_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
