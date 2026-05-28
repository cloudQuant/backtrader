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


class CurrencyProfitsStrategy(bt.Strategy):
    """EA 0641: Dual MA crossover + 6-bar high/low breakout.
    Buy when MA_fast > MA_slow and price <= 6-bar lowest low.
    Sell when MA_fast < MA_slow and price >= 6-bar highest high.
    Exit buy when price >= 6-bar highest high; exit sell when price <= 6-bar lowest low.
    """

    params = dict(
        ma_period_first=32,
        ma_period_second=86,
        stop_loss=170,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ma_fast = bt.indicators.SMA(self.data.close, period=self.p.ma_period_first)
        self.ma_slow = bt.indicators.SMA(self.data.close, period=self.p.ma_period_second)
        self.highest6 = bt.indicators.Highest(self.data.high, period=6)
        self.lowest6 = bt.indicators.Lowest(self.data.low, period=6)

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

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        price = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        highest = float(self.highest6[-1])
        lowest = float(self.lowest6[-1])
        if self.position.size > 0:
            if price >= highest:
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
        else:
            if price <= lowest:
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self) < max(self.p.ma_period_second, 6) + 2:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return

        ma_f = float(self.ma_fast[-1])
        ma_s = float(self.ma_slow[-1])
        price = float(self.data.close[0])
        lowest = float(self.lowest6[-1])
        highest = float(self.highest6[-1])
        sl_dist = float(self.p.stop_loss) * self._point()

        if ma_f > ma_s and price <= lowest:
            self.signal_count += 1
            self.stop_price = self._round(price - sl_dist)
            self.order = self.buy(size=self.p.lots)
        elif ma_f < ma_s and price >= highest:
            self.signal_count += 1
            self.stop_price = self._round(price + sl_dist)
            self.order = self.sell(size=self.p.lots)

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
