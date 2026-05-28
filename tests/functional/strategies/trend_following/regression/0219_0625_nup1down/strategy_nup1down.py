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


class NUp1DownStrategy(bt.Strategy):
    """EA 0625: N bars up then 1 bar down → Sell.
    Each "up" bar must be bullish (close>open) and close higher than previous close.
    Last bar must be bearish (close<open).
    Trailing stop.
    Fixed SL/TP.
    """

    params = dict(
        n_bars_up=3,
        stop_loss=50,
        take_profit=50,
        trailing_stop=10,
        trailing_step=5,
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

    def _trailing(self):
        if not self.position or self.order is not None:
            return
        ts = float(self.p.trailing_stop) * self._point()
        step = float(self.p.trailing_step) * self._point()
        price = float(self.data.close[0])
        if ts <= 0:
            return
        if self.position.size < 0:
            new_sl = self._round(price + ts)
            if self.stop_price is None:
                if price + ts < self.position.price:
                    self.stop_price = self._round(self.position.price)
            elif new_sl + step < float(self.stop_price):
                self.stop_price = new_sl

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size < 0:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        n = int(self.p.n_bars_up)
        if len(self) < n + 3:
            return
        if self.order is not None:
            return
        if self.position:
            self._trailing()
            self._manage_position()
            return

        # Check pattern: bar[0] is bearish, bars[-1..-n] are all bullish with rising closes
        c0 = float(self.data.close[0])
        o0 = float(self.data.open[0])
        if c0 >= o0:
            return  # last bar must be bearish

        pattern_ok = True
        for i in range(1, n + 1):
            ci = float(self.data.close[-i])
            oi = float(self.data.open[-i])
            if ci <= oi:
                pattern_ok = False; break
            if i < n:
                ci_next = float(self.data.close[-(i + 1)])
                if ci <= ci_next:
                    pattern_ok = False; break

        if pattern_ok:
            self.signal_count += 1
            sl = float(self.p.stop_loss) * self._point()
            tp = float(self.p.take_profit) * self._point()
            price = float(self.data.close[0])
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None
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
