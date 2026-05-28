from __future__ import absolute_import, division, print_function, unicode_literals

import io

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


class BreakdownStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=50,
        takeprofit_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        min_distance_pips=25,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.entry_order = None
        self.close_order = None
        self.buy_stop_order = None
        self.sell_stop_order = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None
        self.current_session_date = None
        self.pending_levels_date = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _minimum_bars(self):
        return 2 * 24 * 4 + 10

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None

    def _cancel_pending_orders(self):
        if self.buy_stop_order is not None:
            self.cancel(self.buy_stop_order)
            self.buy_stop_order = None
        if self.sell_stop_order is not None:
            self.cancel(self.sell_stop_order)
            self.sell_stop_order = None

    def _initialize_exit_levels(self):
        if not self.position or self.entry_price is None:
            return
        if self.position.size > 0:
            self.stop_price = self.entry_price - self.p.stoploss_pips * self.p.point_size if self.p.stoploss_pips > 0 else None
            self.limit_price = self.entry_price + self.p.takeprofit_pips * self.p.point_size if self.p.takeprofit_pips > 0 else None
        else:
            self.stop_price = self.entry_price + self.p.stoploss_pips * self.p.point_size if self.p.stoploss_pips > 0 else None
            self.limit_price = self.entry_price - self.p.takeprofit_pips * self.p.point_size if self.p.takeprofit_pips > 0 else None

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _check_exit_thresholds(self):
        if not self.position or self.entry_price is None or self.close_order is not None:
            return False
        bar_high = float(self.data0_feed.high[0])
        bar_low = float(self.data0_feed.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and bar_low <= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_high >= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        else:
            if self.stop_price is not None and bar_high >= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_low <= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        return False

    def _update_trailing(self):
        if not self.position or self.entry_price is None or self.p.trailing_stop_pips <= 0:
            return
        close_price = float(self.data0_feed.close[0])
        trail_distance = self.p.trailing_stop_pips * self.p.point_size
        trail_gate = (self.p.trailing_stop_pips + self.p.trailing_step_pips) * self.p.point_size
        if self.position.size > 0:
            if close_price - self.entry_price > trail_gate:
                candidate = close_price - trail_distance
                if self.stop_price is None or candidate > self.stop_price + 1e-12:
                    self.stop_price = candidate
                    self.log(f'UPDATE LONG TRAIL stop={self.stop_price:.5f}')
        else:
            if self.entry_price - close_price > trail_gate:
                candidate = close_price + trail_distance
                if self.stop_price is None or candidate < self.stop_price - 1e-12:
                    self.stop_price = candidate
                    self.log(f'UPDATE SHORT TRAIL stop={self.stop_price:.5f}')

    def _previous_day_levels(self):
        current_dt = bt.num2date(self.data0_feed.datetime[0])
        prev_day = current_dt.date() - pd.Timedelta(days=1)
        prev_high = None
        prev_low = None
        max_lookback = min(len(self.data0_feed) - 1, 24 * 4 * 7)
        for i in range(1, max_lookback + 1):
            dt_i = bt.num2date(self.data0_feed.datetime[-i])
            day_i = dt_i.date()
            if day_i == current_dt.date():
                continue
            if day_i == prev_day:
                high_i = float(self.data0_feed.high[-i])
                low_i = float(self.data0_feed.low[-i])
                prev_high = high_i if prev_high is None else max(prev_high, high_i)
                prev_low = low_i if prev_low is None else min(prev_low, low_i)
            elif prev_high is not None:
                break
        return prev_high, prev_low

    def _ensure_daily_pending_orders(self):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        current_dt = bt.num2date(self.data0_feed.datetime[0])
        session_date = current_dt.date()
        if self.current_session_date != session_date:
            self._cancel_pending_orders()
            self.current_session_date = session_date
            self.pending_levels_date = None
        if self.pending_levels_date == session_date:
            return
        if self.buy_stop_order is not None or self.sell_stop_order is not None:
            return
        prev_high, prev_low = self._previous_day_levels()
        if prev_high is None or prev_low is None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        min_distance = self.p.min_distance_pips * self.p.point_size
        buy_price = prev_high + min_distance
        sell_price = prev_low - min_distance
        buy_sl = buy_price - self.p.stoploss_pips * self.p.point_size if self.p.stoploss_pips > 0 else None
        buy_tp = buy_price + self.p.takeprofit_pips * self.p.point_size if self.p.takeprofit_pips > 0 else None
        sell_sl = sell_price + self.p.stoploss_pips * self.p.point_size if self.p.stoploss_pips > 0 else None
        sell_tp = sell_price - self.p.takeprofit_pips * self.p.point_size if self.p.takeprofit_pips > 0 else None
        buy_kwargs = dict(size=size, exectype=bt.Order.Stop, price=buy_price)
        sell_kwargs = dict(size=size, exectype=bt.Order.Stop, price=sell_price)
        if buy_sl is not None:
            buy_kwargs['plimit'] = None
        if sell_sl is not None:
            sell_kwargs['plimit'] = None
        self.buy_stop_order = self.buy(**buy_kwargs)
        self.sell_stop_order = self.sell(**sell_kwargs)
        self.pending_levels_date = session_date
        self.log(f'PLACE OCO BUY_STOP={buy_price:.5f} SELL_STOP={sell_price:.5f}')

    def next(self):
        if len(self.data0_feed) < self._minimum_bars():
            return
        if self._check_exit_thresholds():
            return
        self._update_trailing()
        self._ensure_daily_pending_orders()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.buy_stop_order:
                self.entry_order = None
                self.buy_stop_order = None
                self.active_side = 'long'
                self.entry_price = order.executed.price
                self._cancel_pending_orders()
                self.log(f'ENTRY FILLED side=long price={order.executed.price:.5f} size={order.executed.size}')
                self._initialize_exit_levels()
            elif order == self.sell_stop_order:
                self.entry_order = None
                self.sell_stop_order = None
                self.active_side = 'short'
                self.entry_price = order.executed.price
                self._cancel_pending_orders()
                self.log(f'ENTRY FILLED side=short price={order.executed.price:.5f} size={order.executed.size}')
                self._initialize_exit_levels()
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self._reset_exit_levels()
            else:
                if order.isbuy() and order.exectype == bt.Order.Stop:
                    self.buy_stop_order = None
                elif order.issell() and order.exectype == bt.Order.Stop:
                    self.sell_stop_order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.buy_stop_order:
                self.buy_stop_order = None
            elif order == self.sell_stop_order:
                self.sell_stop_order = None
            elif order == self.close_order:
                self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.entry_price = None
            self._reset_exit_levels()
