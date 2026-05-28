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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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


class MtcComboStrategy(bt.Strategy):
    params = dict(
        bar=0,
        ma_period=2,
        ma_shift=0,
        tp1=50.0,
        sl1=50.0,
        x12=100,
        x22=100,
        x32=100,
        x42=100,
        tp2=50.0,
        sl2=50.0,
        p2=20,
        x13=100,
        x23=100,
        x33=100,
        x43=100,
        tp3=50.0,
        sl3=50.0,
        p3=20,
        x14=100,
        x24=100,
        x34=100,
        x44=100,
        p4=20,
        pass_mode=10,
        lot=0.01,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.ma_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _price_delta(self, offset, period):
        if period <= 0:
            return 0.0
        return float(self.data.open[-offset]) - float(self.data.open[-offset - period])

    def _perceptron1(self):
        w1 = self.p.x12 - 100
        w2 = self.p.x22 - 100
        w3 = self.p.x32 - 100
        w4 = self.p.x42 - 100
        a1 = float(self.data.close[0]) - float(self.data.open[-self.p.p2])
        a2 = self._price_delta(self.p.p2, self.p.p2)
        a3 = self._price_delta(self.p.p2 * 2, self.p.p2)
        a4 = self._price_delta(self.p.p2 * 3, self.p.p2)
        return w1 * a1 + w2 * a2 + w3 * a3 + w4 * a4

    def _perceptron2(self):
        w1 = self.p.x13 - 100
        w2 = self.p.x23 - 100
        w3 = self.p.x33 - 100
        w4 = self.p.x43 - 100
        a1 = float(self.data.close[0]) - float(self.data.open[-self.p.p3])
        a2 = self._price_delta(self.p.p3, self.p.p3)
        a3 = self._price_delta(self.p.p3 * 2, self.p.p3)
        a4 = self._price_delta(self.p.p3 * 3, self.p.p3)
        return w1 * a1 + w2 * a2 + w3 * a3 + w4 * a4

    def _perceptron3(self):
        w1 = self.p.x14 - 100
        w2 = self.p.x24 - 100
        w3 = self.p.x34 - 100
        w4 = self.p.x44 - 100
        a1 = float(self.data.close[0]) - float(self.data.open[-self.p.p4])
        a2 = self._price_delta(self.p.p4, self.p.p4)
        a3 = self._price_delta(self.p.p4 * 2, self.p.p4)
        a4 = self._price_delta(self.p.p4 * 3, self.p.p4)
        return w1 * a1 + w2 * a2 + w3 * a3 + w4 * a4

    def _basic_trading_system(self):
        right = float(self.ma[-self.p.bar])
        left = float(self.ma[-self.p.bar - 1])
        return right - left

    def _supervisor(self):
        current_sl = self.p.sl1
        current_tp = self.p.tp1
        signal = self._basic_trading_system()
        if self.p.pass_mode == 4:
            if self._perceptron3() > 0:
                if self._perceptron2() > 0:
                    return 1.0, self.p.sl3, self.p.tp3
            else:
                if self._perceptron1() < 0:
                    return -1.0, self.p.sl2, self.p.tp2
            return signal, current_sl, current_tp
        if self.p.pass_mode == 3:
            if self._perceptron2() > 0:
                return 1.0, self.p.sl3, self.p.tp3
            return signal, current_sl, current_tp
        if self.p.pass_mode == 2:
            if self._perceptron1() < 0:
                return -1.0, self.p.sl2, self.p.tp2
            return signal, current_sl, current_tp
        return signal, current_sl, current_tp

    def _set_risk_prices(self, is_long, price, stop_loss, take_profit):
        self.stop_price = round(price - stop_loss * self.p.point, self.p.price_digits) if is_long else round(price + stop_loss * self.p.point, self.p.price_digits)
        self.take_profit_price = round(price + take_profit * self.p.point, self.p.price_digits) if is_long else round(price - take_profit * self.p.point, self.p.price_digits)

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.ma_period + self.p.bar + 5, self.p.p2 * 4 + 5, self.p.p3 * 4 + 5, self.p.p4 * 4 + 5)
        if len(self.data) < warmup:
            return
        if self.entry_order is not None:
            return
        if self.position:
            high_price = round(float(self.data.high[0]), self.p.price_digits)
            low_price = round(float(self.data.low[0]), self.p.price_digits)
            if self.position.size > 0:
                if low_price <= self.stop_price:
                    self.log(f'close long by stop={self.stop_price:.2f}')
                    self.entry_order = self.close()
                    return
                if high_price >= self.take_profit_price:
                    self.log(f'close long by take_profit={self.take_profit_price:.2f}')
                    self.entry_order = self.close()
                    return
            else:
                if high_price >= self.stop_price:
                    self.log(f'close short by stop={self.stop_price:.2f}')
                    self.entry_order = self.close()
                    return
                if low_price <= self.take_profit_price:
                    self.log(f'close short by take_profit={self.take_profit_price:.2f}')
                    self.entry_order = self.close()
                    return
            return

        signal, stop_loss, take_profit = self._supervisor()
        close_price = round(float(self.data.close[0]), self.p.price_digits)
        if signal > 0:
            self.log(f'buy supervisor={signal:.4f} sl={stop_loss:.2f} tp={take_profit:.2f}')
            self._set_risk_prices(True, close_price, stop_loss, take_profit)
            self.entry_order = self.buy(size=self.p.lot)
        else:
            self.log(f'sell supervisor={signal:.4f} sl={stop_loss:.2f} tp={take_profit:.2f}')
            self._set_risk_prices(False, close_price, stop_loss, take_profit)
            self.entry_order = self.sell(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if order.executed.size > 0:
                self.buy_count += 1
            elif order.executed.size < 0:
                self.sell_count += 1
            if not self.position:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
