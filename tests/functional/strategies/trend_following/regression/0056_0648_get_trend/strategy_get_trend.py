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


class GetTrendStrategy(bt.Strategy):
    """EA 0648: Dual-timeframe MA trend confirmation + Stochastic entry.

    Original uses M15 MA + H1 MA for trend, then Stochastic crossover in
    oversold/overbought zones. Migrated to single-TF with two MA periods
    to approximate multi-TF behavior.
    """

    params = dict(
        ma_period_fast=99,
        ma_period_slow=184,
        stoch_k=27,
        stoch_d=3,
        stoch_slow_d=3,
        porog=10,
        stop_loss=90,
        take_profit=540,
        trailing_stop=20,
        lots=0.1,
        point=0.01,
        price_digits=2,
        relaxed_entries=False,
    )

    def __init__(self):
        self.median_price = (self.data.high + self.data.low) / 2.0
        self.ma_fast = bt.indicators.SmoothedMovingAverage(self.median_price, period=self.p.ma_period_fast)
        self.ma_slow = bt.indicators.SmoothedMovingAverage(self.median_price, period=self.p.ma_period_slow)
        self.stoch = bt.indicators.Stochastic(self.data, period=self.p.stoch_k, period_dfast=self.p.stoch_d, period_dslow=self.p.stoch_slow_d)

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
        price = float(self.data.close[0])
        trail_dist = float(self.p.trailing_stop) * self._point()
        if self.position.size > 0:
            if trail_dist > 0 and price > float(self.position.price):
                new_stop = self._round(price - trail_dist)
                if self.stop_price is None or new_stop > float(self.stop_price):
                    self.stop_price = new_stop
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
        else:
            if trail_dist > 0 and price < float(self.position.price):
                new_stop = self._round(price + trail_dist)
                if self.stop_price is None or new_stop < float(self.stop_price):
                    self.stop_price = new_stop
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        min_len = max(self.p.ma_period_slow, self.p.stoch_k + self.p.stoch_d + self.p.stoch_slow_d) + 2
        if len(self) < min_len:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return

        price = float(self.data.close[0])
        ma_f = float(self.ma_fast[0])
        ma_s = float(self.ma_slow[0])
        porog_dist = float(self.p.porog) * self._point()

        stoch_main_0 = float(self.stoch.percK[0])
        stoch_main_1 = float(self.stoch.percK[-1])
        stoch_sig_0 = float(self.stoch.percD[0])

        if price < ma_f and price < ma_s and (ma_f - price) <= porog_dist:
            if stoch_sig_0 < 20 and stoch_main_0 < 20 and stoch_main_1 < stoch_sig_0 and stoch_main_0 > stoch_sig_0:
                self.signal_count += 1
                self._set_risk('buy', price)
                self.order = self.buy(size=self.p.lots)
                return
            if self.p.relaxed_entries and stoch_main_0 > stoch_main_1:
                self.signal_count += 1
                self._set_risk('buy', price)
                self.order = self.buy(size=self.p.lots)
                return

        if price > ma_f and price > ma_s and (price - ma_f) <= porog_dist:
            if stoch_sig_0 > 80 and stoch_main_0 > 80 and stoch_main_1 > stoch_sig_0 and stoch_main_0 < stoch_sig_0:
                self.signal_count += 1
                self._set_risk('sell', price)
                self.order = self.sell(size=self.p.lots)
                return
            if self.p.relaxed_entries and stoch_main_0 < stoch_main_1:
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
