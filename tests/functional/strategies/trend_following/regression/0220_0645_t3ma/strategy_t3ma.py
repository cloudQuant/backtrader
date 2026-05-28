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


class T3Indicator(bt.Indicator):
    """Tillson T3 moving average — six cascaded EMAs with volume factor."""
    lines = ('t3',)
    params = (('period', 4), ('vfactor', 0.7),)

    def __init__(self):
        e1 = bt.indicators.EMA(self.data, period=self.p.period)
        e2 = bt.indicators.EMA(e1, period=self.p.period)
        e3 = bt.indicators.EMA(e2, period=self.p.period)
        e4 = bt.indicators.EMA(e3, period=self.p.period)
        e5 = bt.indicators.EMA(e4, period=self.p.period)
        e6 = bt.indicators.EMA(e5, period=self.p.period)
        v = self.p.vfactor
        c1 = -(v * v * v)
        c2 = 3 * v * v + 3 * v * v * v
        c3 = -6 * v * v - 3 * v - 3 * v * v * v
        c4 = 1 + 3 * v + v * v * v + 3 * v * v
        self.lines.t3 = c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3


class T3MAStrategy(bt.Strategy):
    """EA 0645: T3MA-ALARM based entry.
    Buy when T3 turns up (T3[0] > T3[-1] and T3[-1] <= T3[-2]).
    Sell when T3 turns down (T3[0] < T3[-1] and T3[-1] >= T3[-2]).
    Fixed SL/TP, single position.
    """

    params = dict(
        t3_period=4,
        t3_vfactor=0.7,
        bar_number=1,
        lots=0.1,
        stop_loss=20,
        take_profit=125,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.t3 = T3Indicator(self.data.close, period=self.p.t3_period, vfactor=self.p.t3_vfactor)
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
        if len(self) < self.p.t3_period * 6 + 3:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return

        bn = int(self.p.bar_number)
        t3_0 = float(self.t3[-bn])
        t3_1 = float(self.t3[-bn - 1])

        price = float(self.data.close[0])
        if t3_0 > 0 and t3_1 == 0:
            self.signal_count += 1
            self._set_risk('buy', price)
            self.order = self.buy(size=self.p.lots)
        elif t3_0 == 0 and t3_1 > 0:
            pass
        else:
            if t3_0 > t3_1:
                cur = float(self.t3[0])
                prev = float(self.t3[-1])
                if cur > prev:
                    self.signal_count += 1
                    self._set_risk('buy', price)
                    self.order = self.buy(size=self.p.lots)
            elif t3_0 < t3_1:
                cur = float(self.t3[0])
                prev = float(self.t3[-1])
                if cur < prev:
                    self.signal_count += 1
                    self._set_risk('sell', price)
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
