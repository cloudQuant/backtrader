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


class TwoMAFourLevelStrategy(bt.Strategy):
    params = dict(
        take_profit=55,
        stop_loss=260,
        lots=1.0,
        calculation_bar=1,
        ma_period_fast=50,
        ma_method_fast='smma',
        ma_period_slow=130,
        ma_method_slow='smma',
        most_top_level=500,
        top_level=250,
        lower_level=250,
        lowermost_level=500,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        median = (self.data.high + self.data.low) / 2.0
        self.ma_fast = bt.indicators.SmoothedMovingAverage(median, period=self.p.ma_period_fast)
        self.ma_slow = bt.indicators.SmoothedMovingAverage(median, period=self.p.ma_period_slow)

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

    def _signal(self):
        idx = -int(self.p.calculation_bar)
        idx_prev = idx - 1
        fast_0 = float(self.ma_fast[idx])
        fast_1 = float(self.ma_fast[idx_prev])
        slow_0 = float(self.ma_slow[idx])
        slow_1 = float(self.ma_slow[idx_prev])
        point = self._point()
        upper_levels = [0.0, float(self.p.most_top_level) * point, float(self.p.top_level) * point]
        lower_levels = [float(self.p.lowermost_level) * point, float(self.p.lower_level) * point]
        if fast_1 <= slow_1 and fast_0 > slow_0:
            return 1
        for level in upper_levels[1:]:
            if fast_1 <= slow_1 + level and fast_0 > slow_0 + level:
                return 1
        for level in lower_levels:
            if fast_1 <= slow_1 - level and fast_0 > slow_0 - level:
                return 1
        if fast_1 >= slow_1 and fast_0 < slow_0:
            return -1
        for level in upper_levels[1:]:
            if fast_1 >= slow_1 + level and fast_0 < slow_0 + level:
                return -1
        for level in lower_levels:
            if fast_1 >= slow_1 - level and fast_0 < slow_0 - level:
                return -1
        return 0

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
        if len(self) < self.p.ma_period_slow + 2:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        signal = self._signal()
        if signal == 0:
            return
        self.signal_count += 1
        price = float(self.data.close[0])
        if signal > 0:
            self._set_risk('buy', price)
            self.order = self.buy(size=self.p.lots)
        else:
            self._set_risk('sell', price)
            self.order = self.sell(size=self.p.lots)

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
