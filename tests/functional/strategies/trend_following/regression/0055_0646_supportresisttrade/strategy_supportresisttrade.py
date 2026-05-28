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


class SupportResistTradeStrategy(bt.Strategy):
    """EA 0646: Support/resistance breakout with MA trend filter and trailing stop."""

    params = dict(
        num_bars=55,
        ma_period=500,
        trailing_stop=10,
        trailing_step=10,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ma = bt.indicators.EMA(self.data.close, period=self.p.ma_period)
        self.highest = bt.indicators.Highest(self.data.high, period=self.p.num_bars)
        self.lowest = bt.indicators.Lowest(self.data.low, period=self.p.num_bars)

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
        ts = float(self.p.trailing_stop) * self._point()
        step = float(self.p.trailing_step) * self._point()
        price = float(self.data.close[0])
        if self.position.size > 0:
            new_sl = self._round(price - ts)
            if self.stop_price is not None and new_sl > float(self.stop_price) + step:
                self.stop_price = new_sl
        elif self.position.size < 0:
            new_sl = self._round(price + ts)
            if self.stop_price is not None and new_sl < float(self.stop_price) - step:
                self.stop_price = new_sl

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        support = float(self.lowest[-1])
        resist = float(self.highest[-1])
        if self.position.size > 0:
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
            if self.position.price <= float(self.data.close[0]) and low < support:
                self.order = self.close(); return
        else:
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return
            if self.position.price >= float(self.data.close[0]) and high > resist:
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self) < max(self.p.num_bars, self.p.ma_period) + 2:
            return
        if self.order is not None:
            return

        support = float(self.lowest[-1])
        resist = float(self.highest[-1])
        ma_val = float(self.ma[0])
        price = float(self.data.close[0])

        if self.position:
            self._trailing()
            self._manage_position()
            return

        if price > ma_val and price > resist:
            self.signal_count += 1
            self.stop_price = self._round(support)
            self.order = self.buy(size=self.p.lots)
        elif price < ma_val and price < support:
            self.signal_count += 1
            self.stop_price = self._round(resist)
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
