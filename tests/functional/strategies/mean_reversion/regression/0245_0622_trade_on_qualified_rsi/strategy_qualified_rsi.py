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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


class QualifiedRSIStrategy(bt.Strategy):
    """EA 0622: Trade on Qualified RSI.
    RSI(28) counter-trend entry with confirmation bars.
    Sell when RSI[1]>=55 AND RSI[2..2+count_bars] all >=55.
    Buy  when RSI[1]<=45 AND RSI[2..2+count_bars] all <=45.
    SL based on close[-1]. Trailing SL modification each bar.
    """

    params = dict(
        rsi_period=28,
        rsi_upper=55,
        rsi_lower=45,
        count_bars=5,
        stop_loss=21,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

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

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _trailing(self):
        if not self.position or self.order is not None:
            return
        sl_dist = float(self.p.stop_loss) * self._point()
        ccl = float(self.data.close[-1])
        if self.position.size > 0:
            new_sl = self._round(ccl - sl_dist)
            if self.stop_price is None or new_sl > float(self.stop_price):
                self.stop_price = new_sl
        elif self.position.size < 0:
            new_sl = self._round(ccl + sl_dist)
            if self.stop_price is None or new_sl < float(self.stop_price):
                self.stop_price = new_sl

    def _check_sl(self):
        if not self.position or self.order is not None or self.stop_price is None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0 and low <= float(self.stop_price):
            self.order = self.close(); return
        if self.position.size < 0 and high >= float(self.stop_price):
            self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        warmup = self.p.rsi_period + self.p.count_bars + 5
        if len(self) < warmup:
            return
        if self.order is not None:
            return
        if self.position:
            self._trailing()
            self._check_sl()
            return

        rsi_1 = float(self.rsi[-1])
        sl_dist = float(self.p.stop_loss) * self._point()

        if rsi_1 >= self.p.rsi_upper:
            qualified = True
            for i in range(2, 3 + self.p.count_bars):
                if float(self.rsi[-i]) < self.p.rsi_upper:
                    qualified = False; break
            if qualified:
                self.signal_count += 1
                price = float(self.data.close[0])
                self.stop_price = self._round(price + sl_dist)
                self.order = self.sell(size=self.p.lots)
                return

        if rsi_1 <= self.p.rsi_lower:
            qualified = True
            for i in range(2, 3 + self.p.count_bars):
                if float(self.rsi[-i]) > self.p.rsi_lower:
                    qualified = False; break
            if qualified:
                self.signal_count += 1
                price = float(self.data.close[0])
                self.stop_price = self._round(price - sl_dist)
                self.order = self.buy(size=self.p.lots)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0: self.buy_count += 1
                elif order.executed.size < 0: self.sell_count += 1
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
        if trade.pnlcomm >= 0: self.win_count += 1
        else: self.loss_count += 1
