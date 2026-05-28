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


class EMAStrategy(bt.Strategy):
    """EA 0633: Dual EMA crossover on PRICE_MEDIAN with virtual SL/TP.
    EMA(5) and EMA(10) on median price.
    After crossover (check=1), wait for confirmation:
      - EMA10 - EMA5 > 2*point and Bid >= Low[-1]+MoveBack → Sell.
      - EMA5 - EMA10 > 2*point and Ask <= High[-1]-MoveBack → Buy.
    Virtual SL/TP based on position entry price.
    """

    params = dict(
        ema_fast_period=5,
        ema_slow_period=10,
        virtual_profit_pips=5,
        move_back=3,
        stop_loss=20,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.median_price = (self.data.high + self.data.low) / 2.0
        self.ema_fast = bt.indicators.EMA(self.median_price, period=self.p.ema_fast_period)
        self.ema_slow = bt.indicators.EMA(self.median_price, period=self.p.ema_slow_period)

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
        self.check = 0

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        price = float(self.data.close[0])
        vtp = float(self.p.virtual_profit_pips) * self._point()
        vsl = float(self.p.stop_loss) * self._point()
        entry = self.position.price
        if self.position.size > 0:
            if price >= entry + vtp:
                self.check = 0; self.order = self.close(); return
            if price <= entry - vsl:
                self.check = 0; self.order = self.close(); return
        else:
            if price <= entry - vtp:
                self.check = 0; self.order = self.close(); return
            if price >= entry + vsl:
                self.check = 0; self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self) < self.p.ema_slow_period + 2:
            return
        if self.order is not None:
            return

        ema_f_0 = float(self.ema_fast[0])
        ema_s_0 = float(self.ema_slow[0])
        ema_f_1 = float(self.ema_fast[-1])
        ema_s_1 = float(self.ema_slow[-1])

        if self.position:
            self._manage_position()
            return

        if ((ema_f_1 > ema_s_1 and ema_f_0 < ema_s_0) or
                (ema_f_1 < ema_s_1 and ema_f_0 > ema_s_0)):
            self.check = 1

        if self.check == 1:
            hi_prev = float(self.data.high[-1])
            lo_prev = float(self.data.low[-1])
            move_back = float(self.p.move_back) * self._point()
            price = float(self.data.close[0])

            if ema_s_0 - ema_f_0 > 2 * self._point() and price >= lo_prev + move_back:
                self.signal_count += 1
                self.check = 0
                self.order = self.sell(size=self.p.lots)
            elif ema_f_0 - ema_s_0 > 2 * self._point() and price <= hi_prev - move_back:
                self.signal_count += 1
                self.check = 0
                self.order = self.buy(size=self.p.lots)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0: self.buy_count += 1
                elif order.executed.size < 0: self.sell_count += 1
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
