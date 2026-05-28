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


class WeightedPrice(bt.Indicator):
    lines = ('weighted',)

    def next(self):
        self.lines.weighted[0] = (
            self.data.high[0] + self.data.low[0] + self.data.close[0] + self.data.close[0]
        ) / 4.0


class MATrend2Strategy(bt.Strategy):
    params = dict(
        fixed_lot=3.0,
        stop_loss_pips=50,
        take_profit_pips=140,
        trailing_stop_pips=15,
        trailing_step_pips=5,
        ma_period=12,
        ma_shift=3,
        type_trading='buy_sell',
        only_one_position=True,
        reverse=False,
        close_opposite=True,
        point_size=0.01,
        verbose=False,
    )

    def __init__(self):
        self.weighted_price = WeightedPrice(self.data)
        self.ma = bt.indicators.WeightedMovingAverage(self.weighted_price, period=self.p.ma_period)
        self.last_bar_dt = None
        self.entry_order = None
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
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_bar(self):
        current = bt.num2date(self.data.datetime[0])
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
        close_price = float(self.data.close[0])
        if self.position.size > 0:
            candidate = close_price - trailing_distance
            if self.stop_price is None:
                return
            if candidate > self.stop_price + trailing_step:
                self.stop_price = candidate
                size = abs(self.position.size)
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.limit_order)
        else:
            candidate = close_price + trailing_distance
            if self.stop_price is None:
                return
            if candidate < self.stop_price - trailing_step:
                self.stop_price = candidate
                size = abs(self.position.size)
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.limit_order)

    def _ma_reference(self):
        ref_index = -1 - int(self.p.ma_shift)
        if len(self.ma) < self.p.ma_period + self.p.ma_shift + 2:
            return None
        return float(self.ma[ref_index])

    def _signal(self):
        ma_ref = self._ma_reference()
        if ma_ref is None:
            return None
        buy_allowed = self.p.type_trading in ('buy', 'buy_sell')
        sell_allowed = self.p.type_trading in ('sell', 'buy_sell')
        close_price = float(self.data.close[0])
        if not self.p.reverse:
            if buy_allowed and close_price > ma_ref:
                return 'buy'
            if sell_allowed and close_price < ma_ref:
                return 'sell'
        else:
            if sell_allowed and close_price > ma_ref:
                return 'sell'
            if buy_allowed and close_price < ma_ref:
                return 'buy'
        return None

    def next(self):
        self.bar_num += 1
        if not self._new_bar():
            return
        if self.position:
            self._update_trailing_stop()
        if self.entry_order is not None:
            return
        signal = self._signal()
        if signal is None:
            return

        if self.position:
            if signal == 'buy' and self.position.size < 0 and self.p.close_opposite:
                self._cancel_exit_orders()
                self.close()
                self.log('CLOSE SHORT BY BUY SIGNAL')
                return
            if signal == 'sell' and self.position.size > 0 and self.p.close_opposite:
                self._cancel_exit_orders()
                self.close()
                self.log('CLOSE LONG BY SELL SIGNAL')
                return
            if self.p.only_one_position:
                return

        size = max(0.01, float(self.p.fixed_lot))
        if signal == 'buy':
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log('OPEN BUY')
        else:
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log('OPEN SELL')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order == self.entry_order:
            if order.status == order.Completed:
                self.entry_order = None
                self._place_exit_orders()
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.entry_order = None
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
