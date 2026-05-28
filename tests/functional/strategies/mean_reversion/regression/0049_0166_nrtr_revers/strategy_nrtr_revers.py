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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class NrtrReversStrategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        point_size=0.01,
        stoploss_pips=50,
        takeprofit_pips=1000,
        trailing_stop_pips=15,
        trailing_step_pips=45,
        atr_period=3,
        reverse_pips=50,
        coeff_of_volatility=3.0,
        initial_trade_state='buy',
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.atr = bt.indicators.AverageTrueRange(self.data0_feed, period=self.p.atr_period)
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_side = None
        self.active_side = None
        self.active_stop_price = None
        self.trade_state = 'buy' if str(self.p.initial_trade_state).lower() != 'sell' else 'sell'
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

    def prenext(self):
        self.next()

    def _new_bar(self):
        current = bt.num2date(self.data0_feed.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _place_exit_orders(self):
        if not self.position:
            return
        size = abs(self.position.size)
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        if self.position.size > 0:
            stop_price = self.position.price - stop_distance if self.p.stoploss_pips > 0 else None
            take_price = self.position.price + take_distance if self.p.takeprofit_pips > 0 else None
            if stop_price is not None:
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=stop_price)
                self.active_stop_price = stop_price
            if take_price is not None:
                self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=take_price, oco=self.stop_order)
        else:
            stop_price = self.position.price + stop_distance if self.p.stoploss_pips > 0 else None
            take_price = self.position.price - take_distance if self.p.takeprofit_pips > 0 else None
            if stop_price is not None:
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=stop_price)
                self.active_stop_price = stop_price
            if take_price is not None:
                self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=take_price, oco=self.stop_order)

    def _apply_trailing(self):
        if not self.position or self.p.trailing_stop_pips <= 0 or self.p.trailing_step_pips <= 0 or self.stop_order is None:
            return
        trail_stop = self.p.trailing_stop_pips * self.p.point_size
        trail_step = self.p.trailing_step_pips * self.p.point_size
        size = abs(self.position.size)
        price = float(self.data0_feed.close[0])
        if self.position.size > 0:
            if price - self.position.price <= trail_stop + trail_step:
                return
            candidate = price - trail_stop
            if self.active_stop_price is None or candidate > self.active_stop_price + trail_step:
                self.cancel(self.stop_order)
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=candidate, oco=self.limit_order)
                self.active_stop_price = candidate
        else:
            if self.position.price - price <= trail_stop + trail_step:
                return
            candidate = price + trail_stop
            if self.active_stop_price is None or candidate < self.active_stop_price - trail_step:
                self.cancel(self.stop_order)
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=candidate, oco=self.limit_order)
                self.active_stop_price = candidate

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.entry_order = self.buy(size=size) if side == 'long' else self.sell(size=size)
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _window_low(self, start_shift, count):
        values = [float(self.data0_feed.low[-shift]) for shift in range(start_shift, start_shift + count)]
        return min(values)

    def _window_high(self, start_shift, count):
        values = [float(self.data0_feed.high[-shift]) for shift in range(start_shift, start_shift + count)]
        return max(values)

    def next(self):
        self.bar_num += 1
        self._apply_trailing()
        min_len = max(self.p.atr_period + 6, 15)
        if len(self.data0_feed) < min_len:
            return
        if not self._new_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        atr_prev = float(self.atr[-1])
        if not math.isfinite(atr_prev):
            return
        different = float(self.p.coeff_of_volatility) * atr_prev
        reverse_distance = self.p.reverse_pips * self.p.point_size
        half_period = max(1, int(round(self.p.atr_period / 2.0)))
        close_1 = float(self.data0_feed.close[-1])

        if self.trade_state == 'buy':
            low = self._window_low(2, max(1, self.p.atr_period - 1))
            line = low - different
            low2 = self._window_low(self.p.atr_period - half_period + 1, half_period)
            if (line - close_1 > different) or (low2 - line >= reverse_distance):
                self.trade_state = 'sell'
                if self.position.size > 0:
                    self._submit_close('trend changed to sell')
                elif not self.position:
                    self._submit_entry('short', 'trend changed to sell while flat')
                return
            return

        if self.trade_state == 'sell':
            high = self._window_high(2, max(1, self.p.atr_period - 1))
            line = high + different
            high2 = self._window_high(self.p.atr_period - half_period + 1, half_period)
            if (close_1 - line > different) or (line - high2 >= reverse_distance):
                self.trade_state = 'buy'
                if self.position.size < 0:
                    self._submit_close('trend changed to buy')
                elif not self.position:
                    self._submit_entry('long', 'trend changed to buy while flat')
                return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                if order.executed.size > 0:
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.entry_order = None
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self._place_exit_orders()
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.active_stop_price = None
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.active_stop_price = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
                self.active_stop_price = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
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
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
