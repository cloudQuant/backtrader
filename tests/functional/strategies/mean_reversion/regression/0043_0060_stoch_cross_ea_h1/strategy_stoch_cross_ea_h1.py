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
    df = df.set_index('datetime').sort_index()
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


class StochCrossEAH1Strategy(bt.Strategy):
    params = dict(
        risk_percent=5.0,
        stoch_k_period=14,
        stoch_d_period=3,
        slowing=7,
        cooldown_minutes=60,
        stop_loss_points=300,
        take_profit_points=300,
        lot_size=0.1,
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
    )

    def __init__(self):
        self.data_feed = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.stoch = bt.indicators.Stochastic(
            self.data_feed,
            period=self.p.stoch_k_period,
            period_dfast=self.p.slowing,
            period_dslow=self.p.stoch_d_period,
        )
        self.crossover = bt.indicators.CrossOver(self.stoch.percK, self.stoch.percD)
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.close_order = None
        self.last_trade_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_reentry_direction = None

    def log(self, text):
        dt = bt.num2date(self.data_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        lot = min(max(lot, self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def _cooldown_ready(self, now):
        if self.last_trade_dt is None:
            return True
        delta_seconds = (now - self.last_trade_dt).total_seconds()
        return delta_seconds >= self.p.cooldown_minutes * 60

    def _cancel_exit_orders(self):
        if self.stop_order is not None and self.stop_order.alive():
            self.cancel(self.stop_order)
        if self.limit_order is not None and self.limit_order.alive():
            self.cancel(self.limit_order)

    def _submit_long_bracket(self):
        size = self._normalize_lot(self.p.lot_size)
        entry_price = float(self.data_feed.close[0])
        stop_price = round(entry_price - self.p.stop_loss_points * self.p.point_size, 2)
        limit_price = round(entry_price + self.p.take_profit_points * self.p.point_size, 2)
        orders = self.buy_bracket(size=size, stopprice=stop_price, limitprice=limit_price)
        self.entry_order, self.stop_order, self.limit_order = orders
        self.entry_order.addinfo(kind='entry_long')

    def _submit_short_bracket(self):
        size = self._normalize_lot(self.p.lot_size)
        entry_price = float(self.data_feed.close[0])
        stop_price = round(entry_price + self.p.stop_loss_points * self.p.point_size, 2)
        limit_price = round(entry_price - self.p.take_profit_points * self.p.point_size, 2)
        orders = self.sell_bracket(size=size, stopprice=stop_price, limitprice=limit_price)
        self.entry_order, self.stop_order, self.limit_order = orders
        self.entry_order.addinfo(kind='entry_short')

    def _reverse_to_long(self):
        self._cancel_exit_orders()
        self.pending_reentry_direction = 'long'
        self.close_order = self.close()
        if self.close_order is not None:
            self.close_order.addinfo(kind='close_short')

    def _reverse_to_short(self):
        self._cancel_exit_orders()
        self.pending_reentry_direction = 'short'
        self.close_order = self.close()
        if self.close_order is not None:
            self.close_order.addinfo(kind='close_long')

    def next(self):
        self.bar_num += 1
        min_bars = self.p.stoch_k_period + self.p.slowing + self.p.stoch_d_period
        if len(self.data_feed) < min_bars:
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        now = bt.num2date(self.data_feed.datetime[0]).replace(tzinfo=None)
        if not self._cooldown_ready(now):
            return
        signal_up = self.crossover[0] > 0
        signal_down = self.crossover[0] < 0
        if self.position.size > 0:
            if signal_down:
                self._reverse_to_short()
            return
        if self.position.size < 0:
            if signal_up:
                self._reverse_to_long()
            return
        if signal_up:
            self._submit_long_bracket()
        elif signal_down:
            self._submit_short_bracket()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        kind = getattr(order.info, 'kind', None)
        if order.status == order.Completed:
            executed_dt = bt.num2date(order.executed.dt).replace(tzinfo=None)
            if kind == 'entry_long':
                self.buy_count += 1
                self.last_trade_dt = executed_dt
                self.log(f'long entry price={order.executed.price:.2f} volume={order.executed.size:.4f}')
            elif kind == 'entry_short':
                self.sell_count += 1
                self.last_trade_dt = executed_dt
                self.log(f'short entry price={order.executed.price:.2f} volume={abs(order.executed.size):.4f}')
            elif kind in ('close_long', 'close_short'):
                self.log(f'reversal close price={order.executed.price:.2f}')
                if self.pending_reentry_direction == 'long':
                    self.pending_reentry_direction = None
                    self._submit_long_bracket()
                elif self.pending_reentry_direction == 'short':
                    self.pending_reentry_direction = None
                    self._submit_short_bracket()
        elif order.status in (order.Canceled, order.Margin, order.Rejected):
            if kind in ('entry_long', 'entry_short'):
                self.log(f'entry failed status={order.getstatusname()}')
            elif kind in ('close_long', 'close_short'):
                self.pending_reentry_direction = None
        if order is self.entry_order and not order.alive():
            self.entry_order = None
        if order is self.stop_order and not order.alive():
            self.stop_order = None
        if order is self.limit_order and not order.alive():
            self.limit_order = None
        if order is self.close_order and not order.alive():
            self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
