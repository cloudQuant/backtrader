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


class MTCNeuralNetworkPlusMACDStrategy(bt.Strategy):
    params = dict(
        x11=100,
        x12=100,
        x13=100,
        x14=100,
        tp1=100.0,
        sl1=50.0,
        p1=10,
        x21=100,
        x22=100,
        x23=100,
        x24=100,
        tp2=100.0,
        sl2=50.0,
        p2=10,
        x31=100,
        x32=100,
        x33=100,
        x34=100,
        p3=10,
        pass_level=3,
        m_lots=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.macd = bt.indicators.MACD(self.data.close, period_me1=12, period_me2=26, period_signal=9)

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

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _perceptron(self, weights, period):
        w1, w2, w3, w4 = weights
        a1 = float(self.data.close[0]) - float(self.data.open[-period])
        a2 = float(self.data.open[-period]) - float(self.data.open[-period * 2])
        a3 = float(self.data.open[-period * 2]) - float(self.data.open[-period * 3])
        a4 = float(self.data.open[-period * 3]) - float(self.data.open[-period * 4])
        return w1 * a1 + w2 * a2 + w3 * a3 + w4 * a4

    def _perceptron1(self):
        return self._perceptron((self.p.x11 - 100, self.p.x12 - 100, self.p.x12 - 100, self.p.x12 - 100), int(self.p.p1))

    def _perceptron2(self):
        return self._perceptron((self.p.x21 - 100, self.p.x22 - 100, self.p.x23 - 100, self.p.x24 - 100), int(self.p.p2))

    def _perceptron3(self):
        return self._perceptron((self.p.x31 - 100, self.p.x32 - 100, self.p.x33 - 100, self.p.x34 - 100), int(self.p.p3))

    def _supervisor(self):
        stop_loss = None
        take_profit = None
        if int(self.p.pass_level) >= 3:
            if self._perceptron3() > 0:
                if self._perceptron2() > 0:
                    stop_loss = float(self.p.sl2)
                    take_profit = float(self.p.tp2)
                    return 1, stop_loss, take_profit
            else:
                if self._perceptron1() < 0:
                    stop_loss = float(self.p.sl1)
                    take_profit = float(self.p.tp1)
                    return -1, stop_loss, take_profit
            return 0, None, None
        if int(self.p.pass_level) == 2:
            if self._perceptron2() > 0:
                return 1, float(self.p.sl2), float(self.p.tp2)
            return 0, None, None
        if int(self.p.pass_level) == 1:
            if self._perceptron1() < 0:
                return -1, float(self.p.sl1), float(self.p.tp1)
            return 0, None, None
        return 0, None, None

    def _macd_signal(self):
        macd_current = float(self.macd.macd[0])
        macd_previous = float(self.macd.macd[-2])
        signal_current = float(self.macd.signal[0])
        signal_previous = float(self.macd.signal[-2])
        if macd_current < 0 and macd_current >= signal_current and macd_previous <= signal_previous:
            return 1
        if macd_current > 0 and macd_current <= signal_current and macd_previous >= signal_previous:
            return -1
        return 0

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
        else:
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        need_bars = max(int(self.p.p1), int(self.p.p2), int(self.p.p3)) * 4 + 5
        if len(self) < need_bars:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        macd_signal = self._macd_signal()
        perceptron, stop_loss, take_profit = self._supervisor()
        if macd_signal > 0 and perceptron > 0:
            self.signal_count += 1
            unit = self._unit()
            price = float(self.data.close[0])
            self.stop_price = round(price - float(stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(take_profit) * unit, int(self.p.price_digits))
            self.order = self.buy(size=self.p.m_lots)
            return
        if macd_signal < 0 and perceptron < 0:
            self.signal_count += 1
            unit = self._unit()
            price = float(self.data.close[0])
            self.stop_price = round(price + float(stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(take_profit) * unit, int(self.p.price_digits))
            self.order = self.sell(size=self.p.m_lots)

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
