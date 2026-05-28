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


class AIS1Strategy(bt.Strategy):
    """AIS1: multi-timeframe OHLC breakout with trailing stop.

    Original EA uses D1 and H4 bars to compute average, then enters on
    breakout above prior high or below prior low. Since we run on a single
    timeframe data feed, we approximate by using the available bar's
    high/low/close with configurable lookback.
    """

    params = dict(
        account_reserve=0.20,
        order_reserve=0.04,
        take_factor=0.8,
        stop_factor=1.0,
        trail_factor=5.0,
        trail_stepping=1.0,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
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

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        price = float(self.data.close[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
            if price > float(self.position.price):
                trail_dist = float(self.p.trail_factor) * self._point() * 10
                trail_step = float(self.p.trail_stepping) * self._point() * 10
                new_sl = self._round(price - trail_dist)
                if self.stop_price is not None and new_sl > float(self.stop_price) + trail_step:
                    self.stop_price = new_sl
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return
            if price < float(self.position.price):
                trail_dist = float(self.p.trail_factor) * self._point() * 10
                trail_step = float(self.p.trail_stepping) * self._point() * 10
                new_sl = self._round(price + trail_dist)
                if self.stop_price is not None and new_sl < float(self.stop_price) - trail_step:
                    self.stop_price = new_sl

    def next(self):
        self.bar_num += 1
        if len(self) < 3:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return

        prev_high = float(self.data.high[-1])
        prev_low = float(self.data.low[-1])
        prev_close = float(self.data.close[-1])
        avg = (prev_high + prev_low) / 2.0
        price = float(self.data.close[0])

        spread = (prev_high - prev_low)
        stop_dist = spread * float(self.p.stop_factor)
        take_dist = spread * float(self.p.take_factor)

        if prev_close > avg and price > prev_high:
            self.signal_count += 1
            self.stop_price = self._round(prev_high - stop_dist)
            self.take_profit_price = self._round(price + take_dist)
            self.order = self.buy(size=self.p.lots)
        elif prev_close < avg and price < prev_low:
            self.signal_count += 1
            self.stop_price = self._round(prev_low + stop_dist)
            self.take_profit_price = self._round(price - take_dist)
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
                self.stop_price = None; self.take_profit_price = None
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
