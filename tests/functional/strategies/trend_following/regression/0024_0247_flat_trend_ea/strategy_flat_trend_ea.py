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


class FlatTrendIndicator(bt.Indicator):
    lines = ('sell', 'buy', 'end_sell', 'end_buy')

    def __init__(self):
        self.adx = bt.indicators.AverageDirectionalMovementIndex(self.data)
        self.di_plus = bt.indicators.PlusDirectionalIndicator(self.data)
        self.di_minus = bt.indicators.MinusDirectionalIndicator(self.data)
        self.sar = bt.indicators.ParabolicSAR(self.data)
        self.addminperiod(20)

    def next(self):
        sell = buy = end_sell = end_buy = 0.0
        if self.sar[0] < self.data.close[0]:
            if self.di_plus[0] > self.di_minus[0]:
                buy = 1.0
            else:
                end_buy = 1.0
        else:
            if self.di_plus[0] > self.di_minus[0]:
                end_sell = 1.0
            else:
                sell = 1.0
        self.lines.sell[0] = sell
        self.lines.buy[0] = buy
        self.lines.end_sell[0] = end_sell
        self.lines.end_buy[0] = end_buy


class FlatTrendEAStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=50,
        takeprofit_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        use_hour=True,
        start_hour=10,
        end_hour=19,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.indicator = FlatTrendIndicator(self.signal_data)
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.active_side = None
        self.last_bar_dt = None
        self.active_stop_price = None
        self.active_take_price = None

    def log(self, text):
        dt = bt.num2date(self.exec_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def prenext(self):
        self.next()

    def _new_bar(self):
        current = bt.num2date(self.exec_data.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _allow_trading_hour(self):
        if not self.p.use_hour:
            return True
        hour = bt.num2date(self.exec_data.datetime[0]).hour
        return self.p.start_hour <= hour < self.p.end_hour

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
                self.active_take_price = take_price
        else:
            stop_price = self.position.price + stop_distance if self.p.stoploss_pips > 0 else None
            take_price = self.position.price - take_distance if self.p.takeprofit_pips > 0 else None
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

    def _close_side(self, reason):
        if not self.position:
            return
        self._cancel_exit_orders()
        self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

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
        if len(self.signal_data) < 20:
            return
        sell = float(self.indicator.sell[0])
        buy = float(self.indicator.buy[0])
        end_sell = float(self.indicator.end_sell[0])
        end_buy = float(self.indicator.end_buy[0])
        if buy == 1.0 or end_sell == 1.0 or end_buy == 1.0:
            if self.position.size < 0:
                self._close_side('buy/end signal closes short')
        if sell == 1.0 or end_sell == 1.0 or end_buy == 1.0:
            if self.position.size > 0:
                self._close_side('sell/end signal closes long')
        if not self._new_bar():
            return
        if not self._allow_trading_hour():
            return
        if self.position or self.entry_order is not None:
            return
        if buy == 1.0:
            self._submit_entry('long', 'FlatTrend buy')
        elif sell == 1.0:
            self._submit_entry('short', 'FlatTrend sell')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_order = None
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
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
