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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class MAStrategy(bt.Strategy):
    params = dict(
        stop_loss=100,
        take_profit=100,
        ma_period=57,
        ma_period1=3,
        ea_magic=12345,
        lot=1.0,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.ma_fast = bt.ind.WeightedMovingAverage(self.data.close, period=self.p.ma_period1)
        self.ma_slow = bt.ind.ExponentialMovingAverage(self.data.close, period=self.p.ma_period)

        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
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
        self.last_bar_dt = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _set_risk_prices(self, side):
        price = float(self.data.close[0])
        unit = self._trade_unit()
        if side == 'buy':
            self.stop_price = round(price - self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def _buy_conditions(self):
        return (
            self.ma_slow[0] > self.ma_slow[-1] > self.ma_slow[-2]
            and self.ma_fast[0] > self.ma_fast[-1] > self.ma_fast[-2]
            and self.data.close[-1] > self.ma_slow[-1]
            and self.ma_slow[0] > self.ma_fast[0]
        )

    def _sell_conditions(self):
        return (
            self.ma_slow[0] < self.ma_slow[-1] < self.ma_slow[-2]
            and self.data.close[-1] < self.ma_slow[-1]
            and self.ma_fast[0] < self.ma_fast[-1] < self.ma_fast[-2]
            and self.ma_slow[0] < self.ma_fast[0]
        )

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(self.p.ma_period, self.p.ma_period1) + 3:
            return
        if self.order is not None:
            return
        dt = bt.num2date(self.data.datetime[0])
        if self.last_bar_dt == dt:
            return
        self.last_bar_dt = dt
        if self._manage_risk():
            return

        buy_opened = self.position.size > 0
        sell_opened = self.position.size < 0
        buy_condition = self._buy_conditions()
        sell_condition = self._sell_conditions()
        self.log(
            'ma fast={0:.5f} slow={1:.5f} buy_condition={2} sell_condition={3}'.format(
                float(self.ma_fast[0]), float(self.ma_slow[0]), buy_condition, sell_condition
            )
        )

        if buy_condition:
            self.buy_signal_count += 1
            if buy_opened:
                return
            if sell_opened:
                self.order = self.close()
                return
            self._set_risk_prices('buy')
            self.order = self.buy(size=self.p.lot)
            return

        if sell_condition:
            self.sell_signal_count += 1
            if sell_opened:
                return
            if buy_opened:
                self.order = self.close()
                return
            self._set_risk_prices('sell')
            self.order = self.sell(size=self.p.lot)

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
