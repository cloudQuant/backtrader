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
    keep_cols = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']
    if 'spread' in df.columns:
        keep_cols.append('spread')
    df = df[keep_cols]
    if 'spread' not in df.columns:
        df['spread'] = 0
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


class BrandyStrategy(bt.Strategy):
    params = dict(
        lot=0.10,
        stop_loss_pips=50,
        take_profit_pips=150,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        ma_close_period=20,
        ma_close_shift=0,
        ma_close_signal_bar=0,
        ma_open_period=70,
        ma_open_shift=0,
        ma_open_signal_bar=0,
        point=0.01,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.ma_open = bt.indicators.ExponentialMovingAverage(self.data0.close, period=self.p.ma_open_period)
        self.ma_close = bt.indicators.ExponentialMovingAverage(self.data0.close, period=self.p.ma_close_period)
        self.order = None
        self.pending_action = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_dt = None
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        dt = bt.num2date(self.data0.datetime[0])
        if self.last_dt == dt:
            return
        self.last_dt = dt
        if len(self.data0) < max(self.p.ma_open_period, self.p.ma_close_period) + 5:
            return
        if self.order is not None:
            return

        ma_open_1 = self._line_value(self.ma_open, 1)
        ma_open_signal_bar = self._line_value(self.ma_open, int(self.p.ma_open_signal_bar))
        ma_close_1 = self._line_value(self.ma_close, 1)
        ma_close_signal_bar = self._line_value(self.ma_open, int(self.p.ma_close_signal_bar))
        if None in (ma_open_1, ma_open_signal_bar, ma_close_1, ma_close_signal_bar):
            return

        if not self.position:
            ask = float(self.data0.close[0])
            bid = float(self.data0.close[0])
            if ma_open_1 > ma_open_signal_bar and ma_close_1 > ma_close_signal_bar:
                self.pending_action = 'open_long'
                self.order = self.buy(size=float(self.p.lot))
                self.log(f'OPEN LONG ma_open_1={ma_open_1:.5f} ma_open_signal={ma_open_signal_bar:.5f} ma_close_1={ma_close_1:.5f} ma_close_signal={ma_close_signal_bar:.5f}')
                self._prepare_entry_levels('long', ask)
                return
            if ma_open_1 < ma_open_signal_bar and ma_close_1 < ma_close_signal_bar:
                self.pending_action = 'open_short'
                self.order = self.sell(size=float(self.p.lot))
                self.log(f'OPEN SHORT ma_open_1={ma_open_1:.5f} ma_open_signal={ma_open_signal_bar:.5f} ma_close_1={ma_close_1:.5f} ma_close_signal={ma_close_signal_bar:.5f}')
                self._prepare_entry_levels('short', bid)
                return

        self._check_exit_levels()
        self._apply_trailing(ma_open_1, ma_open_signal_bar)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.pending_action == 'open_long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self.entry_price = float(order.executed.price)
                self._prepare_entry_levels('long', self.entry_price)
            elif self.pending_action == 'open_short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self.entry_price = float(order.executed.price)
                self._prepare_entry_levels('short', self.entry_price)
            elif self.pending_action == 'close' and not self.position:
                self._clear_trade_levels()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            self.pending_action = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f}')
        if not self.position:
            self._clear_trade_levels()

    def _check_exit_levels(self):
        high_0 = float(self.data0.high[0])
        low_0 = float(self.data0.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low_0 <= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and high_0 >= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG take_profit={self.take_profit_price:.5f}')
                return True
            return False
        if self.position.size < 0:
            if self.stop_price is not None and high_0 >= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE SHORT stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and low_0 <= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE SHORT take_profit={self.take_profit_price:.5f}')
                return True
        return False

    def _apply_trailing(self, ma_open_1, ma_open_signal_bar):
        if not self.position or self.order is not None:
            return
        if self.position.size > 0:
            if ma_open_1 < ma_open_signal_bar:
                self.pending_action = 'close'
                self.order = self.close()
                self.log('CLOSE LONG ma_open reverse')
                return
            if float(self.p.trailing_stop_pips) <= 0:
                return
            trigger = self._distance(self.p.trailing_stop_pips) + self._distance(self.p.trailing_step_pips)
            current_price = float(self.data0.close[0])
            if current_price - self.entry_price > trigger:
                candidate = current_price - self._distance(self.p.trailing_stop_pips)
                if self.stop_price is None or self.stop_price < current_price - trigger:
                    self.stop_price = candidate
                elif candidate > self.stop_price:
                    self.stop_price = candidate
            return
        if ma_open_1 > ma_open_signal_bar:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE SHORT ma_open reverse')
            return
        if float(self.p.trailing_stop_pips) <= 0:
            return
        trigger = self._distance(self.p.trailing_stop_pips) + self._distance(self.p.trailing_step_pips)
        current_price = float(self.data0.close[0])
        if self.entry_price - current_price > trigger:
            candidate = current_price + self._distance(self.p.trailing_stop_pips)
            if self.stop_price is None or self.stop_price == 0:
                self.stop_price = candidate
            elif candidate < self.stop_price:
                self.stop_price = candidate

    def _prepare_entry_levels(self, side, reference_price):
        self.entry_price = float(reference_price)
        if side == 'long':
            self.stop_price = self.entry_price - self._distance(self.p.stop_loss_pips) if self.p.stop_loss_pips else None
            self.take_profit_price = self.entry_price + self._distance(self.p.take_profit_pips) if self.p.take_profit_pips else None
        else:
            self.stop_price = self.entry_price + self._distance(self.p.stop_loss_pips) if self.p.stop_loss_pips else None
            self.take_profit_price = self.entry_price - self._distance(self.p.take_profit_pips) if self.p.take_profit_pips else None

    def _clear_trade_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    @staticmethod
    def _line_value(line, ago=0):
        value = float(line[-ago] if ago else line[0])
        if not math.isfinite(value):
            return None
        return value

    def _distance(self, pips):
        return float(pips) * float(self.p.point)
