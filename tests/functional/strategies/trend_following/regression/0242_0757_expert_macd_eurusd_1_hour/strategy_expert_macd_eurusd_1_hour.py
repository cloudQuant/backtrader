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


class ExpertMacdEurusd1HourStrategy(bt.Strategy):
    params = dict(
        trailing=25,
        risk=0.01,
        macd_fast=5,
        macd_slow=15,
        macd_signal=3,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        min_lot=0.01,
    )

    def __init__(self):
        self.macd = bt.indicators.MACD(self.data.close, period_me1=self.p.macd_fast, period_me2=self.p.macd_slow, period_signal=self.p.macd_signal)
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

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _lots_optimized(self):
        volume = round(float(self.broker.getcash()) * float(self.p.risk) / 1000.0, 2)
        return max(volume, float(self.p.min_lot))

    def _mac(self, line, index):
        return float(line[-index]) if index > 0 else float(line[0])

    def _buy_signal(self):
        mac1 = self._mac(self.macd.macd, 0)
        mac2 = self._mac(self.macd.macd, 1)
        mac3 = self._mac(self.macd.macd, 2)
        mac4 = self._mac(self.macd.macd, 3)
        sig1 = self._mac(self.macd.signal, 0)
        sig2 = self._mac(self.macd.signal, 1)
        sig3 = self._mac(self.macd.signal, 2)
        sig4 = self._mac(self.macd.signal, 3)
        return sig4 > sig3 and sig3 > sig2 and sig2 < sig1 and mac4 > mac3 and mac3 < mac2 and mac2 < mac1 and mac2 < -0.00020 and mac4 < 0 and mac1 > 0.00020

    def _sell_signal(self):
        mac1 = self._mac(self.macd.macd, 0)
        mac2 = self._mac(self.macd.macd, 1)
        mac3 = self._mac(self.macd.macd, 2)
        mac4 = self._mac(self.macd.macd, 3)
        sig1 = self._mac(self.macd.signal, 0)
        sig2 = self._mac(self.macd.signal, 1)
        sig3 = self._mac(self.macd.signal, 2)
        sig4 = self._mac(self.macd.signal, 3)
        return sig4 < sig3 and sig3 < sig2 and sig2 > sig1 and mac4 < mac3 and mac3 > mac2 and mac2 > mac1 and mac2 > 0.00020 and mac4 > 0 and mac1 < -0.00035

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        mac1 = self._mac(self.macd.macd, 0)
        mac2 = self._mac(self.macd.macd, 1)
        close_price = float(self.data.close[0])
        unit = self._unit()
        if self.position.size > 0:
            if mac1 < mac2:
                self.order = self.close()
                return True
            if self.p.trailing > 0 and close_price - self.position.price > unit * float(self.p.trailing):
                new_stop = round(close_price - unit * float(self.p.trailing), int(self.p.price_digits))
                if self.stop_price is None or new_stop > self.stop_price:
                    self.stop_price = new_stop
            if self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
                self.order = self.close()
                return True
        else:
            if mac1 > mac2:
                self.order = self.close()
                return True
            if self.p.trailing > 0 and self.position.price - close_price > unit * float(self.p.trailing):
                new_stop = round(close_price + unit * float(self.p.trailing), int(self.p.price_digits))
                if self.stop_price is None or new_stop < self.stop_price:
                    self.stop_price = new_stop
            if self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < 10:
            return
        if self.order is not None:
            return
        if self.position:
            if self._manage_position():
                return
            return
        if self._buy_signal():
            self.signal_count += 1
            volume = self._lots_optimized()
            self.order = self.buy(size=volume)
            self.stop_price = None
            self.log(f'buy signal volume={volume:.2f}')
            return
        if self._sell_signal():
            self.signal_count += 1
            volume = self._lots_optimized()
            self.order = self.sell(size=volume)
            self.stop_price = None
            self.log(f'sell signal volume={volume:.2f}')

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
