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


class AwesomeOscillator(bt.Indicator):
    lines = ('ao',)
    params = dict(fast=5, slow=34)

    def __init__(self):
        median = (self.data.high + self.data.low) / 2.0
        fast_ma = bt.indicators.SimpleMovingAverage(median, period=self.p.fast)
        slow_ma = bt.indicators.SimpleMovingAverage(median, period=self.p.slow)
        self.lines.ao = fast_ma - slow_ma


class AcceleratorOscillator(bt.Indicator):
    lines = ('ac',)

    def __init__(self):
        ao = AwesomeOscillator(self.data)
        ao_sma = bt.indicators.SimpleMovingAverage(ao.ao, period=5)
        self.lines.ac = ao.ao - ao_sma


class ArtificialIntelligenceStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        stop_loss=850,
        shift=1,
        x1=135,
        x2=127,
        x3=16,
        x4=93,
        point=0.01,
    )

    def __init__(self):
        self.ac = AcceleratorOscillator(self.data)

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

        self.addminperiod(int(self.p.shift) + 25)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _perceptron(self):
        s = int(self.p.shift)
        a1 = float(self.ac[-s])
        a2 = float(self.ac[-(s + 7)])
        a3 = float(self.ac[-(s + 14)])
        a4 = float(self.ac[-(s + 21)])
        w1 = int(self.p.x1) - 100
        w2 = int(self.p.x2) - 100
        w3 = int(self.p.x3) - 100
        w4 = int(self.p.x4) - 100
        return w1 * a1 + w2 * a2 + w3 * a3 + w4 * a4

    def _profit_threshold_reached(self):
        if not self.position or self.stop_price is None:
            return False
        stop_distance = float(self.p.point) * float(self.p.stop_loss)
        spread_distance = float(self.p.point)
        threshold = stop_distance * 2.0 + spread_distance
        if self.position.size > 0:
            return float(self.data.close[0]) > float(self.stop_price) + threshold
        return float(self.data.close[0]) < float(self.stop_price) - threshold

    def _check_stop_exit(self):
        if not self.position or self.order is not None or self.stop_price is None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0 and low <= self.stop_price:
            self.log(f'close long by stop={self.stop_price:.5f}')
            self.order = self.close()
            return True
        if self.position.size < 0 and high >= self.stop_price:
            self.log(f'close short by stop={self.stop_price:.5f}')
            self.order = self.close()
            return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        if self._check_stop_exit():
            return

        perc = self._perceptron()
        open_buy = perc > 0
        open_sell = perc < 0
        if (open_buy and not open_sell) or (open_sell and not open_buy):
            self.signal_count += 1
        lot = max(round(float(self.p.lots), 2), 0.01)
        px = float(self.data.close[0])

        if self.position:
            if self._profit_threshold_reached():
                if self.position.size > 0:
                    if open_sell:
                        new_lot = round(abs(float(self.position.size)) + lot, 2)
                        self.stop_price = px + float(self.p.point) * float(self.p.stop_loss)
                        self.log(f'rotate buy->sell perc={perc:.5f} lot={new_lot:.2f}')
                        self.order = self.sell(size=new_lot)
                        return
                    self.stop_price = float(self.position.price)
                    return
                if self.position.size < 0:
                    if open_buy:
                        new_lot = round(abs(float(self.position.size)) + lot, 2)
                        self.stop_price = px - float(self.p.point) * float(self.p.stop_loss)
                        self.log(f'rotate sell->buy perc={perc:.5f} lot={new_lot:.2f}')
                        self.order = self.buy(size=new_lot)
                        return
                    self.stop_price = float(self.position.price)
                    return
            return

        if open_buy and not open_sell:
            self.stop_price = px - float(self.p.point) * float(self.p.stop_loss)
            self.log(f'buy signal perc={perc:.5f} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if open_sell and not open_buy:
            self.stop_price = px + float(self.p.point) * float(self.p.stop_loss)
            self.log(f'sell signal perc={perc:.5f} lot={lot:.2f}')
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
