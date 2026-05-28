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


class GordagoEAStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_buy_pips=40,
        takeprofit_buy_pips=70,
        stoploss_sell_pips=10,
        takeprofit_sell_pips=40,
        trailing_stop_pips=5,
        trailing_step_pips=1,
        sto_level_buy=37.0,
        sto_level_sell=96.0,
        macd_signal_period=9,
        macd_fast_ema_period=12,
        macd_slow_ema_period=26,
        sto_kperiod=5,
        sto_dperiod=3,
        sto_slowing=3,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.work_data = self.datas[1]
        self.macd_data = self.datas[2]
        self.sto_data = self.datas[3]
        self.macd = bt.indicators.MACD(
            self.macd_data,
            period_me1=self.p.macd_fast_ema_period,
            period_me2=self.p.macd_slow_ema_period,
            period_signal=self.p.macd_signal_period,
        )
        self.stochastic = bt.indicators.Stochastic(
            self.sto_data,
            period=self.p.sto_kperiod,
            period_dfast=self.p.sto_dperiod,
            period_dslow=self.p.sto_slowing,
            movav=bt.indicators.ExponentialMovingAverage,
        )
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.active_side = None
        self.last_work_dt = None
        self.active_stop_price = None
        self.active_take_price = None

    def log(self, text):
        dt = bt.num2date(self.exec_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def prenext(self):
        self.next()

    def _new_work_bar(self):
        current = bt.num2date(self.work_data.datetime[0])
        if self.last_work_dt == current:
            return False
        self.last_work_dt = current
        return True

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None
        self.active_stop_price = None
        self.active_take_price = None

    def _place_exit_orders(self):
        if not self.position:
            return
        size = abs(self.position.size)
        if self.position.size > 0:
            stop_distance = self.p.stoploss_buy_pips * self.p.point_size
            take_distance = self.p.takeprofit_buy_pips * self.p.point_size
            stop_price = self.position.price - stop_distance if self.p.stoploss_buy_pips > 0 else None
            take_price = self.position.price + take_distance if self.p.takeprofit_buy_pips > 0 else None
            if stop_price is not None:
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=stop_price)
                self.active_stop_price = stop_price
            if take_price is not None:
                self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=take_price, oco=self.stop_order)
                self.active_take_price = take_price
        else:
            stop_distance = self.p.stoploss_sell_pips * self.p.point_size
            take_distance = self.p.takeprofit_sell_pips * self.p.point_size
            stop_price = self.position.price + stop_distance if self.p.stoploss_sell_pips > 0 else None
            take_price = self.position.price - take_distance if self.p.takeprofit_sell_pips > 0 else None
            if stop_price is not None:
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=stop_price)
                self.active_stop_price = stop_price
            if take_price is not None:
                self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=take_price, oco=self.stop_order)
                self.active_take_price = take_price

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        if side == 'long':
            self.entry_order = self.buy(size=size)
        else:
            self.entry_order = self.sell(size=size)
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _apply_trailing(self):
        if not self.position or self.p.trailing_stop_pips <= 0 or self.p.trailing_step_pips <= 0:
            return
        if self.entry_order is not None:
            return
        trail_stop = self.p.trailing_stop_pips * self.p.point_size
        trail_step = self.p.trailing_step_pips * self.p.point_size
        price = float(self.exec_data.close[0])
        size = abs(self.position.size)
        if self.position.size > 0:
            if price - self.position.price <= trail_stop + trail_step:
                return
            candidate = price - trail_stop
            if self.active_stop_price is None or candidate > self.active_stop_price + trail_step:
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=candidate, oco=self.limit_order)
                self.active_stop_price = candidate
        else:
            if self.position.price - price <= trail_stop + trail_step:
                return
            candidate = price + trail_stop
            if self.active_stop_price is None or candidate < self.active_stop_price - trail_step:
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=candidate, oco=self.limit_order)
                self.active_stop_price = candidate

    def next(self):
        self._apply_trailing()
        min_bars = max(self.p.macd_slow_ema_period + self.p.macd_signal_period + 3, self.p.sto_kperiod + self.p.sto_dperiod + self.p.sto_slowing + 3)
        if len(self.macd_data) < min_bars or len(self.sto_data) < min_bars:
            return
        if not self._new_work_bar():
            return
        if self.position or self.entry_order is not None:
            return
        macd_now = float(self.macd.macd[0])
        macd_prev = float(self.macd.macd[-1])
        sto_now = float(self.stochastic.percK[0])
        sto_prev = float(self.stochastic.percK[-1])
        if macd_now > macd_prev and macd_prev < 0.0 and sto_now < self.p.sto_level_buy and sto_now > sto_prev:
            self._submit_entry('long', 'MACD up + Stochastic buy filter')
            return
        if macd_now < macd_prev and macd_prev > 0.0 and sto_now > self.p.sto_level_sell and sto_now < sto_prev:
            self._submit_entry('short', 'MACD down + Stochastic sell filter')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
                self._place_exit_orders()
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.active_stop_price = None
                self.active_take_price = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
                self.active_stop_price = None
                self.active_take_price = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.active_stop_price = None
            self.active_take_price = None
