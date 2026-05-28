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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume']
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class GazonkosStrategy(bt.Strategy):
    params = dict(
        take_profit=16,
        rollback=16,
        stop_loss=40,
        t1=3,
        t2=2,
        delta=40,
        lots=0.1,
        active_trades=1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.state = 0
        self.trade_direction = 0
        self.maxprice = None
        self.minprice = None
        self.last_trade_hour = None
        self.last_signal_hour = None

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.order = None
        self.stop_price = None
        self.take_profit_price = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _current_hour(self):
        return bt.num2date(self.data.datetime[0]).hour

    def _open_positions_count(self):
        return 1 if self.position else 0

    def _can_trade(self):
        current_hour = self._current_hour()
        if self.last_trade_hour is not None and current_hour == self.last_trade_hour:
            return False
        if self._open_positions_count() >= int(self.p.active_trades):
            return False
        return True

    def _set_risk(self, side, price):
        if side == 'buy':
            self.stop_price = self._round(price - float(self.p.stop_loss) * self._point())
            self.take_profit_price = self._round(price + float(self.p.take_profit) * self._point())
        else:
            self.stop_price = self._round(price + float(self.p.stop_loss) * self._point())
            self.take_profit_price = self._round(price - float(self.p.take_profit) * self._point())

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

    def next(self):
        self.bar_num += 1
        if len(self) < max(int(self.p.t1), int(self.p.t2)) + 2:
            return
        if self.order is not None:
            return
        self._manage_position()
        current_hour = self._current_hour()

        if self.state == 0:
            if self._can_trade():
                self.state = 1

        if self.state == 1:
            if float(self.data.close[-int(self.p.t2)]) - float(self.data.close[-int(self.p.t1)]) > float(self.p.delta) * self._point():
                self.trade_direction = 1
                self.maxprice = float(self.data.close[0])
                self.last_signal_hour = current_hour
                self.state = 2
            elif float(self.data.close[-int(self.p.t1)]) - float(self.data.close[-int(self.p.t2)]) > float(self.p.delta) * self._point():
                self.trade_direction = -1
                self.minprice = float(self.data.close[0])
                self.last_signal_hour = current_hour
                self.state = 2

        if self.state == 2:
            if self.last_signal_hour != current_hour:
                self.state = 0
                return
            if self.trade_direction == 1:
                if float(self.data.close[0]) > float(self.maxprice):
                    self.maxprice = float(self.data.close[0])
                if float(self.data.close[0]) < float(self.maxprice) - float(self.p.rollback) * self._point():
                    self.state = 3
            elif self.trade_direction == -1:
                if float(self.data.close[0]) < float(self.minprice):
                    self.minprice = float(self.data.close[0])
                if float(self.data.close[0]) > float(self.minprice) + float(self.p.rollback) * self._point():
                    self.state = 3

        if self.state == 3:
            price = float(self.data.close[0])
            if self.trade_direction == 1:
                self._set_risk('buy', price)
                self.signal_count += 1
                self.order = self.buy(size=self.p.lots)
                self.last_trade_hour = current_hour
                self.state = 0
            elif self.trade_direction == -1:
                self._set_risk('sell', price)
                self.signal_count += 1
                self.order = self.sell(size=self.p.lots)
                self.last_trade_hour = current_hour
                self.state = 0

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
