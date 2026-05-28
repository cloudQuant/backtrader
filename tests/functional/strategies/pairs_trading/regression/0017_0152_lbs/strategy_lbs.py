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


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class LbsStrategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        point_size=0.01,
        stoploss_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=15,
        atr_period=3,
        hour_1=10,
        hour_2=11,
        hour_3=12,
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.datas[0], period=self.p.atr_period)
        self.buy_entry_order = None
        self.sell_entry_order = None
        self.stop_exit_order = None
        self.entry_order = None
        self.active_side = None
        self.last_bar_dt = None
        self.last_schedule_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.datas[0].datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_bar(self):
        current = bt.num2date(self.datas[0].datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _scheduled_hour(self):
        dt = bt.num2date(self.datas[0].datetime[0])
        return dt.hour in {int(self.p.hour_1), int(self.p.hour_2), int(self.p.hour_3)}

    def _cancel_pending_entries(self):
        if self.buy_entry_order is not None:
            self.cancel(self.buy_entry_order)
            self.buy_entry_order = None
        if self.sell_entry_order is not None:
            self.cancel(self.sell_entry_order)
            self.sell_entry_order = None

    def _cancel_stop_exit(self):
        if self.stop_exit_order is not None:
            self.cancel(self.stop_exit_order)
            self.stop_exit_order = None

    def _submit_entry_pair(self):
        if len(self) < 2:
            return
        dt = bt.num2date(self.datas[0].datetime[0])
        if self.last_schedule_dt == dt:
            return
        if self.buy_entry_order is not None or self.sell_entry_order is not None:
            return
        self.last_schedule_dt = dt
        highest = max(float(self.datas[0].high[0]), float(self.datas[0].high[-1]))
        lowest = min(float(self.datas[0].low[0]), float(self.datas[0].low[-1]))
        size = max(0.01, float(self.p.fixed_lot))
        self._cancel_pending_entries()
        self.buy_entry_order = self.buy(exectype=bt.Order.Stop, price=highest, size=size)
        self.sell_entry_order = self.sell(exectype=bt.Order.Stop, price=lowest, size=size, oco=self.buy_entry_order)
        self.log(f'PLACE ENTRY PAIR buy_stop={highest:.5f} sell_stop={lowest:.5f} size={size}')

    def _ensure_initial_stop(self):
        if not self.position or self.stop_exit_order is not None:
            return
        if self.active_side is None:
            self.active_side = 'long' if self.position.size > 0 else 'short'
        stop_distance = self.p.stoploss_pips * self.p.point_size
        if self.position.size > 0:
            stop_price = self.position.price - stop_distance
            self.stop_exit_order = self.sell(size=abs(self.position.size), exectype=bt.Order.Stop, price=stop_price)
        else:
            stop_price = self.position.price + stop_distance
            self.stop_exit_order = self.buy(size=abs(self.position.size), exectype=bt.Order.Stop, price=stop_price)
        self.log(f'PLACE PROTECTIVE STOP side={self.active_side} stop={stop_price:.5f}')

    def _trail_stop(self):
        if not self.position:
            return
        trailing_stop = self.p.trailing_stop_pips * self.p.point_size
        trailing_step = self.p.trailing_step_pips * self.p.point_size
        trigger_distance = trailing_stop + trailing_step
        if self.position.size > 0:
            if (self.datas[0].close[0] - self.position.price) <= trigger_distance:
                return
            desired = float(self.datas[0].close[0]) - trailing_stop
            current = None if self.stop_exit_order is None else float(self.stop_exit_order.created.price)
            if current is not None and desired <= current + 1e-12:
                return
            self._cancel_stop_exit()
            self.stop_exit_order = self.sell(size=abs(self.position.size), exectype=bt.Order.Stop, price=desired)
            self.log(f'TRAIL LONG stop={desired:.5f}')
        else:
            if (self.position.price - self.datas[0].close[0]) <= trigger_distance:
                return
            desired = float(self.datas[0].close[0]) + trailing_stop
            current = None if self.stop_exit_order is None else float(self.stop_exit_order.created.price)
            if current is not None and desired >= current - 1e-12:
                return
            self._cancel_stop_exit()
            self.stop_exit_order = self.buy(size=abs(self.position.size), exectype=bt.Order.Stop, price=desired)
            self.log(f'TRAIL SHORT stop={desired:.5f}')

    def next(self):
        self.bar_num += 1
        if len(self) < max(3, self.p.atr_period + 1):
            return
        if not self._new_bar():
            return
        if self.position:
            if self.active_side is None:
                self.active_side = 'long' if self.position.size > 0 else 'short'
            self._ensure_initial_stop()
            self._trail_stop()
            return
        self._cancel_stop_exit()
        if self._scheduled_hour():
            self._submit_entry_pair()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.buy_entry_order:
                self.active_side = 'long'
                self.buy_count += 1
                self._cancel_pending_entries()
                self.buy_entry_order = None
                self.log(f'BUY ENTRY FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self._ensure_initial_stop()
            elif order == self.sell_entry_order:
                self.active_side = 'short'
                self.sell_count += 1
                self._cancel_pending_entries()
                self.sell_entry_order = None
                self.log(f'SELL ENTRY FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self._ensure_initial_stop()
            elif order == self.stop_exit_order:
                self.stop_exit_order = None
                self.active_side = None
                self.log(f'STOP EXIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.buy_entry_order:
                self.buy_entry_order = None
            elif order == self.sell_entry_order:
                self.sell_entry_order = None
            elif order == self.stop_exit_order:
                self.stop_exit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
