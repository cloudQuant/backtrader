from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class AppliedPriceCCI(bt.Indicator):
    lines = ('cci',)
    params = dict(period=14, factor=0.015)

    def __init__(self):
        self.addminperiod(int(self.p.period) + 1)

    def next(self):
        period = int(self.p.period)
        prices = [float(self.data[-i]) for i in range(period)]
        mean_price = sum(prices) / period
        mean_dev = sum(abs(price - mean_price) for price in prices) / period
        denom = float(self.p.factor) * mean_dev
        if denom == 0:
            self.lines.cci[0] = 0.0
            return
        self.lines.cci[0] = (float(self.data[0]) - mean_price) / denom


class ComboRightStrategy(bt.Strategy):
    params = dict(
        tp1=500,
        sl1=500,
        cci_period=10,
        cci_price=1,
        x12=100,
        x22=100,
        x32=100,
        x42=100,
        tp2=500,
        sl2=500,
        p2=20,
        x13=100,
        x23=100,
        x33=100,
        x43=100,
        tp3=500,
        sl3=500,
        p3=20,
        x14=100,
        x24=100,
        x34=100,
        x44=100,
        p4=20,
        mode_pass=4,
        lots=0.1,
        shift=1,
        point=0.01,
    )

    def __init__(self):
        self.cci = AppliedPriceCCI(self._price_line(self.p.cci_price), period=self.p.cci_period)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self.stop_price = None
        self.take_price = None
        self._position_was_open = False
        self.sl = float(self.p.sl1)
        self.tp = float(self.p.tp1)

        max_shift = max(int(self.p.shift) + int(self.p.p2) * 4, int(self.p.shift) + int(self.p.p3) * 4, int(self.p.shift) + int(self.p.p4) * 4)
        self.addminperiod(max(self.p.cci_period, max_shift) + 5)

    def _price_line(self, price_code):
        code = int(price_code)
        if code == 0:
            return self.data.close
        if code == 1:
            return self.data.open
        if code == 2:
            return self.data.high
        if code == 3:
            return self.data.low
        if code == 4:
            return (self.data.high + self.data.low) / 2.0
        if code == 5:
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if code == 6:
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        return self.data.open

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _perceptron(self, shifts, weights):
        close_1 = float(self.data.close[-shifts[0]])
        close_2 = float(self.data.close[-shifts[1]])
        close_3 = float(self.data.close[-shifts[2]])
        close_4 = float(self.data.close[-shifts[3]])
        close_5 = float(self.data.close[-shifts[4]])
        a1 = close_1 - close_2
        a2 = close_2 - close_3
        a3 = close_3 - close_4
        a4 = close_4 - close_5
        return weights[0] * a1 + weights[1] * a2 + weights[2] * a3 + weights[3] * a4

    def _basic_signal(self):
        idx = -int(self.p.shift) if int(self.p.shift) > 0 else 0
        return float(self.cci[idx])

    def _supervisor(self):
        basic_sig = self._basic_signal()
        signal = basic_sig
        self.sl = float(self.p.sl1)
        self.tp = float(self.p.tp1)

        pass_value = int(self.p.mode_pass)
        shift = int(self.p.shift)

        sell_weights = [int(self.p.x12) - 100, int(self.p.x22) - 100, int(self.p.x32) - 100, int(self.p.x42) - 100]
        buy_weights = [int(self.p.x13) - 100, int(self.p.x23) - 100, int(self.p.x33) - 100, int(self.p.x43) - 100]
        sum_weights = [int(self.p.x14) - 100, int(self.p.x24) - 100, int(self.p.x34) - 100, int(self.p.x44) - 100]

        sell_shifts = [shift, shift + int(self.p.p2), shift + int(self.p.p2) * 2, shift + int(self.p.p2) * 3, shift + int(self.p.p2) * 4]
        buy_shifts = [shift, shift + int(self.p.p3), shift + int(self.p.p3) * 2, shift + int(self.p.p3) * 3, shift + int(self.p.p3) * 4]
        sum_shifts = [shift, shift + int(self.p.p4), shift + int(self.p.p4) * 2, shift + int(self.p.p4) * 3, shift + int(self.p.p4) * 4]

        if pass_value == 4:
            output1 = self._perceptron(sell_shifts, sell_weights)
            output2 = self._perceptron(buy_shifts, buy_weights)
            output3 = self._perceptron(sum_shifts, sum_weights)
            if output3 > 0 and output2 > 0:
                self.sl = float(self.p.sl3)
                self.tp = float(self.p.tp3)
                return 1.0
            if output3 <= 0 and output1 < 0:
                self.sl = float(self.p.sl2)
                self.tp = float(self.p.tp2)
                return -1.0
            return basic_sig

        if pass_value == 3:
            output2 = self._perceptron(buy_shifts, buy_weights)
            if output2 > 0:
                self.sl = float(self.p.sl3)
                self.tp = float(self.p.tp3)
                return 1.0
            return basic_sig

        if pass_value == 2:
            output1 = self._perceptron(sell_shifts, sell_weights)
            if output1 < 0:
                self.sl = float(self.p.sl2)
                self.tp = float(self.p.tp2)
                return -1.0
            return basic_sig

        return basic_sig

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        if self._check_exit_levels():
            return
        if self.position:
            return

        signal = self._supervisor()
        if signal > 0 or signal < 0:
            self.signal_count += 1
        lot = max(round(float(self.p.lots), 2), 0.01)
        px = float(self.data.close[0])

        if signal > 0:
            self.stop_price = px - float(self.p.point) * float(self.sl) if self.sl > 0 else None
            self.take_price = px + float(self.p.point) * float(self.tp) if self.tp > 0 else None
            self.log(f'buy signal signal={signal:.5f} sl={self.sl:.1f} tp={self.tp:.1f} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if signal < 0:
            self.stop_price = px + float(self.p.point) * float(self.sl) if self.sl > 0 else None
            self.take_price = px - float(self.p.point) * float(self.tp) if self.tp > 0 else None
            self.log(f'sell signal signal={signal:.5f} sl={self.sl:.1f} tp={self.tp:.1f} lot={lot:.2f}')
            self.order = self.sell(size=lot)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
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
        self.stop_price = None
        self.take_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
