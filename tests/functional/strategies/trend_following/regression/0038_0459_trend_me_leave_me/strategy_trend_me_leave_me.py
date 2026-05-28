from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class TrendMeLeaveMeStrategy(bt.Strategy):
    params = dict(
        stop_loss_points=10,
        take_profit_points=40,
        breakeven_points=0,
        adx_period=14,
        sar_step=0.02,
        sar_maximum=0.2,
        volume=0.1,
        point=0.01,
    )

    def __init__(self):
        self.adx = bt.ind.ADX(self.data, period=self.p.adx_period)
        self.sar = bt.ind.ParabolicSAR(self.data, af=self.p.sar_step, afmax=self.p.sar_maximum)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.stop_price = None
        self.take_profit_price = None
        self.next_cmd = 'buy'
        self.current_direction = None
        self.breakeven_armed = False

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None
        self.current_direction = None
        self.breakeven_armed = False

    def _set_risk(self, price, direction):
        stop_distance = self.p.stop_loss_points * self.p.point
        take_distance = self.p.take_profit_points * self.p.point
        self.current_direction = direction
        self.breakeven_armed = False
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price + take_distance if self.p.take_profit_points > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price - take_distance if self.p.take_profit_points > 0 else None

    def _update_next_cmd_from_exit(self, exit_reason):
        if self.current_direction is None:
            return
        if exit_reason == 'tp':
            self.next_cmd = 'sell' if self.current_direction > 0 else 'buy'
        elif exit_reason == 'sl':
            self.next_cmd = 'buy' if self.current_direction > 0 else 'sell'

    def _maybe_move_to_breakeven(self):
        if not self.position or self.p.breakeven_points <= 0 or self.breakeven_armed:
            return
        distance = self.p.breakeven_points * self.p.point
        if self.position.size > 0:
            if float(self.data.close[0]) - self.position.price > distance:
                self.stop_price = self.position.price
                self.breakeven_armed = True
        else:
            if self.position.price - float(self.data.close[0]) > distance:
                self.stop_price = self.position.price
                self.breakeven_armed = True

    def _check_exit_levels(self):
        if not self.position:
            self._clear_risk()
            return False
        self._maybe_move_to_breakeven()
        if self.position.size > 0:
            if self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
                self._update_next_cmd_from_exit('sl')
                self.order = self.close()
                return True
            if self.take_profit_price is not None and float(self.data.high[0]) >= self.take_profit_price:
                self._update_next_cmd_from_exit('tp')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
                self._update_next_cmd_from_exit('sl')
                self.order = self.close()
                return True
            if self.take_profit_price is not None and float(self.data.low[0]) <= self.take_profit_price:
                self._update_next_cmd_from_exit('tp')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(self.p.adx_period + 2, 5):
            return
        if self.order:
            return
        if self._check_exit_levels():
            return
        if self.position:
            return

        close = float(self.data.close[0])
        sar = float(self.sar[0])
        adx = float(self.adx[0])
        if sar != sar or adx != adx or close == 0.0:
            return

        if self.next_cmd == 'buy':
            if sar < close and adx < 20:
                self.order = self.buy(size=self.p.volume)
        elif self.next_cmd == 'sell':
            if sar > close and adx < 20:
                self.order = self.sell(size=self.p.volume)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and order.executed.size > 0:
                self.buy_count += 1
                if self.position.size > 0:
                    self._set_risk(order.executed.price, 1)
            elif order.issell() and order.executed.size < 0:
                self.sell_count += 1
                if self.position.size < 0:
                    self._set_risk(order.executed.price, -1)
            elif self.position.size == 0:
                self._clear_risk()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self._clear_risk()
