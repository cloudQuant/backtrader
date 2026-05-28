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


class CrossMAStrategy(bt.Strategy):
    params = dict(
        input_lots=0.1,
        maximum_risk=0.02,
        decrease_factor=3,
        ma1_period=12,
        ma_shift=0,
        ma2_period=4,
        atr_period=6,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        min_lot=0.1,
    )

    def __init__(self):
        self.ma_slow = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.ma1_period)
        self.ma_fast = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.ma2_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.loss_streak = 0

        self.order = None
        self.stop_price = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _lots_optimized(self):
        lot = round(float(self.broker.getcash()) * float(self.p.maximum_risk) / 1000.0, 1)
        if self.p.decrease_factor > 0 and self.loss_streak > 1:
            lot = round(lot - lot * self.loss_streak / float(self.p.decrease_factor), 1)
        return max(lot, float(self.p.min_lot))

    def _sell_cross(self):
        return self.ma_fast[0] < self.ma_slow[0] and self.ma_fast[-1] >= self.ma_slow[-1]

    def _buy_cross(self):
        return self.ma_fast[0] > self.ma_slow[0] and self.ma_fast[-1] <= self.ma_slow[-1]

    def _manage_stop(self):
        if not self.position or self.order is not None or self.stop_price is None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0 and low <= self.stop_price:
            self.order = self.close()
            return True
        if self.position.size < 0 and high >= self.stop_price:
            self.order = self.close()
            return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < max(self.p.ma1_period, self.p.ma2_period) + 2:
            return
        if self.order is not None:
            return
        if self._manage_stop():
            return
        sell_cross = self._sell_cross()
        buy_cross = self._buy_cross()
        if self.position:
            if self.position.size > 0 and sell_cross:
                self.signal_count += 1
                self.order = self.close()
                return
            if self.position.size < 0 and buy_cross:
                self.signal_count += 1
                self.order = self.close()
                return
        if self.position:
            return
        if sell_cross:
            self.signal_count += 1
            lots = self._lots_optimized()
            self.stop_price = round(float(self.data.close[0]) + float(self.atr[0]), int(self.p.price_digits))
            self.order = self.sell(size=lots)
            self.log(f'sell cross lots={lots:.2f} stop={self.stop_price:.2f}')
            return
        if buy_cross:
            self.signal_count += 1
            lots = self._lots_optimized()
            self.stop_price = round(float(self.data.close[0]) - float(self.atr[0]), int(self.p.price_digits))
            self.order = self.buy(size=lots)
            self.log(f'buy cross lots={lots:.2f} stop={self.stop_price:.2f}')

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
            self.loss_streak = 0
        else:
            self.loss_count += 1
            self.loss_streak += 1
