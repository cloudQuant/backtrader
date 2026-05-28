from __future__ import absolute_import, division, print_function, unicode_literals

import io
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


class ForceIndexEma(bt.Indicator):
    lines = ('value',)
    params = dict(period=24)

    def __init__(self):
        raw = (self.data.close - self.data.close(-1)) * self.data.volume
        self.lines.value = bt.indicators.ExponentialMovingAverage(raw, period=self.p.period)


class TDSGlobalStrategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        stop_loss_pips=50,
        take_profit_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        point_size=0.01,
        verbose=False,
    )

    def __init__(self):
        self.data_work = self.datas[0]
        self.data_h4 = self.datas[1]
        self.macd_h4 = bt.indicators.MACD(self.data_h4.close, period_me1=12, period_me2=26, period_signal=9)
        self.osma_h4 = self.macd_h4.macd - self.macd_h4.signal
        self.force_h4 = ForceIndexEma(self.data_h4, period=24)
        self.last_work_bar_dt = None
        self.pending_order = None
        self.pending_side = None
        self.stop_order = None
        self.limit_order = None
        self.stop_price = None
        self.limit_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        if not self.p.verbose:
            return
        dt = bt.num2date(self.data_work.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_work_bar(self):
        current = bt.num2date(self.data_work.datetime[0])
        if self.last_work_bar_dt == current:
            return False
        self.last_work_bar_dt = current
        return True

    def _cancel_pending(self):
        if self.pending_order is not None:
            self.cancel(self.pending_order)
            self.pending_order = None
            self.pending_side = None

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None
        self.stop_price = None
        self.limit_price = None

    def _place_exit_orders(self):
        if not self.position:
            return
        self._cancel_exit_orders()
        stop_distance = float(self.p.stop_loss_pips) * float(self.p.point_size)
        limit_distance = float(self.p.take_profit_pips) * float(self.p.point_size)
        size = abs(self.position.size)
        if self.position.size > 0:
            if stop_distance > 0:
                self.stop_price = self.position.price - stop_distance
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            if limit_distance > 0:
                self.limit_price = self.position.price + limit_distance
                self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=self.limit_price, oco=self.stop_order)
        else:
            if stop_distance > 0:
                self.stop_price = self.position.price + stop_distance
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            if limit_distance > 0:
                self.limit_price = self.position.price - limit_distance
                self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=self.limit_price, oco=self.stop_order)

    def _update_trailing_stop(self):
        if not self.position or self.p.trailing_stop_pips <= 0:
            return
        trailing_distance = float(self.p.trailing_stop_pips) * float(self.p.point_size)
        trailing_step = float(self.p.trailing_step_pips) * float(self.p.point_size)
        close_price = float(self.data_work.close[0])
        if self.position.size > 0:
            if close_price - self.position.price <= trailing_distance + trailing_step:
                return
            candidate = close_price - trailing_distance
            if self.stop_price is None or candidate > self.stop_price + trailing_step:
                self.stop_price = candidate
                size = abs(self.position.size)
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.limit_order)
        else:
            if self.position.price - close_price <= trailing_distance + trailing_step:
                return
            candidate = close_price + trailing_distance
            if self.stop_price is None or candidate < self.stop_price - trailing_step:
                self.stop_price = candidate
                size = abs(self.position.size)
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.limit_order)

    def _signal_state(self):
        if len(self.data_h4) < 4:
            return None
        osma_1 = float(self.osma_h4[-1])
        osma_2 = float(self.osma_h4[-2])
        force_1 = float(self.force_h4.value[-1])
        osma_direction = 1 if osma_1 > osma_2 else -1 if osma_1 < osma_2 else 0
        force_pos = force_1 > 0.0
        force_neg = force_1 < 0.0
        return osma_direction, force_pos, force_neg

    def _maybe_place_limit(self, osma_direction, force_pos, force_neg):
        if self.pending_order is not None or self.position:
            return
        current_close = float(self.data_work.close[0])
        prev_high = float(self.data_work.high[-1])
        prev_low = float(self.data_work.low[-1])
        min_distance = 16.0 * float(self.p.point_size)
        stop_distance = float(self.p.stop_loss_pips) * float(self.p.point_size)
        take_distance = float(self.p.take_profit_pips) * float(self.p.point_size)
        size = max(0.01, float(self.p.fixed_lot))
        if osma_direction == 1 and force_neg:
            price_open = prev_high + float(self.p.point_size)
            price = price_open if price_open > (current_close - min_distance) else current_close + min_distance
            if price - current_close >= min_distance:
                sl = price + stop_distance if stop_distance > 0 else None
                tp = price - take_distance if take_distance > 0 else None
                self.pending_order = self.sell(size=size, exectype=bt.Order.Limit, price=price)
                self.pending_side = 'sell'
                self.log(f'PLACE SELL LIMIT {price:.2f}')
                return
        if osma_direction == -1 and force_pos:
            price_open = prev_low - float(self.p.point_size)
            price = price_open if price_open < (current_close + min_distance) else current_close + min_distance
            if current_close - price >= min_distance:
                sl = price - stop_distance if stop_distance > 0 else None
                tp = price + take_distance if take_distance > 0 else None
                self.pending_order = self.buy(size=size, exectype=bt.Order.Limit, price=price)
                self.pending_side = 'buy'
                self.log(f'PLACE BUY LIMIT {price:.2f}')

    def _maybe_delete_pending(self, osma_direction):
        if self.pending_order is None or self.position:
            return
        if self.pending_side == 'buy' and osma_direction == -1:
            self._cancel_pending()
            self.log('CANCEL BUY LIMIT BY OSMA')
            return
        if self.pending_side == 'sell' and osma_direction == 1:
            self._cancel_pending()
            self.log('CANCEL SELL LIMIT BY OSMA')

    def next(self):
        self.bar_num += 1
        if not self._new_work_bar():
            return
        signal_state = self._signal_state()
        if signal_state is None:
            return
        osma_direction, force_pos, force_neg = signal_state
        self._update_trailing_stop()
        if self.position:
            return
        self._maybe_delete_pending(osma_direction)
        self._maybe_place_limit(osma_direction, force_pos, force_neg)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order == self.pending_order:
            if order.status == order.Completed:
                if order.isbuy():
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.pending_order = None
                self.pending_side = None
                self._place_exit_orders()
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected, order.Expired]:
                self.pending_order = None
                self.pending_side = None
                return
        if order == self.stop_order:
            if order.status == order.Completed:
                self.stop_order = None
                self.limit_order = None
                self.stop_price = None
                self.limit_price = None
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.stop_order = None
                return
        if order == self.limit_order:
            if order.status == order.Completed:
                self.limit_order = None
                self.stop_order = None
                self.stop_price = None
                self.limit_price = None
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._cancel_exit_orders()
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
