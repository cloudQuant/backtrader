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


class MACDStrategy(bt.Strategy):
    """EA 0628: MACD histogram "trend continuation" pattern.
    Buy: histogram peaks above +peak_threshold, then dips below +dip_threshold,
         then reverses up (local valley crossing +0.0005 while still above zero).
    Sell: mirror logic below zero.
    Fixed SL/TP.
    """

    params = dict(
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        peak_threshold=0.0015,
        dip_threshold=0.0005,
        stop_loss=70,
        take_profit=60,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal,
        )
        self.macd_hist = self.macd.macd - self.macd.signal

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
        # State machine for buy signal
        self.buy_stops = 0  # 1 after peak > threshold
        self.buy_s = 0      # 1 after dip below dip_threshold
        self.buy_ok = 0
        # State machine for sell signal
        self.sell_stops1 = 0
        self.sell_s1 = 0
        self.sell_ok = 0

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _set_risk(self, side, price):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if side == 'buy':
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self) < self.p.macd_slow + self.p.macd_signal + 5:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return

        h1 = float(self.macd_hist[-1])
        h2 = float(self.macd_hist[-2])
        h3 = float(self.macd_hist[-3])
        peak = float(self.p.peak_threshold)
        dip = float(self.p.dip_threshold)

        # Buy state machine
        if h1 > peak and self.buy_stops == 0:
            self.buy_stops = 1
        if h1 < dip and self.buy_stops == 1:
            self.buy_stops = 0
            self.buy_s = 1
        if self.buy_s == 1 and h1 > h2 and h2 < h3 and h1 > dip and h2 < dip:
            self.buy_ok = 1
            self.buy_s = 0
        if h1 < 0:
            self.buy_stops = 0; self.buy_ok = 0; self.buy_s = 0

        # Sell state machine
        if h1 < -peak and self.sell_stops1 == 0:
            self.sell_stops1 = 1
        if h1 > -dip and self.sell_stops1 == 1:
            self.sell_stops1 = 0
            self.sell_s1 = 1
        if self.sell_s1 == 1 and h1 < h2 and h2 > h3 and h1 < -dip and h2 > -dip:
            self.sell_ok = 1
            self.sell_s1 = 0
        if h1 > 0:
            self.sell_stops1 = 0; self.sell_ok = 0; self.sell_s1 = 0

        price = float(self.data.close[0])
        if self.buy_ok == 1:
            self.signal_count += 1
            self._set_risk('buy', price)
            self.order = self.buy(size=self.p.lots)
            self.buy_ok = 0
        elif self.sell_ok == 1:
            self.signal_count += 1
            self._set_risk('sell', price)
            self.order = self.sell(size=self.p.lots)
            self.sell_ok = 0

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
