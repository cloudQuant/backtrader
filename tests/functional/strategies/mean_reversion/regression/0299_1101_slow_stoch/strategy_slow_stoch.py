from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader.feeds as btfeeds
import backtrader.indicators as btind
from backtrader.indicator import Indicator
from backtrader.strategy import Strategy
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class SlowStoch(Indicator):
    lines = ('sto', 'signal')
    params = dict(
        k_period=5,
        d_period=3,
        slowing=3,
        xlength=5,
    )

    def __init__(self):
        stoch = btind.StochasticFull(
            self.data,
            period=max(int(self.p.k_period), 1),
            period_dfast=max(int(self.p.d_period), 1),
            period_dslow=max(int(self.p.slowing), 1),
            safediv=True,
        )
        self.l.sto = btind.ExponentialMovingAverage(stoch.percD, period=max(int(self.p.xlength), 1))
        self.l.signal = btind.ExponentialMovingAverage(stoch.percDSlow, period=max(int(self.p.xlength), 1))


class SlowStochStrategy(Strategy):
    params = dict(
        mode='twist',
        signal_bar=1,
        k_period=5,
        d_period=3,
        slowing=3,
        xlength=5,
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
    )

    def __init__(self):
        self.indicator = SlowStoch(
            self.data,
            k_period=self.p.k_period,
            d_period=self.p.d_period,
            slowing=self.p.slowing,
            xlength=self.p.xlength,
        )
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.pending_entry_direction = 0
        self.warmup = int(self.p.k_period + self.p.d_period + self.p.slowing + self.p.xlength + max(int(self.p.signal_bar), 1) + 5)

    def _signal_indexes(self):
        current = -max(int(self.p.signal_bar), 1)
        previous = current - 1
        older = current - 2
        return current, previous, older

    def _breakdown_signals(self):
        current, previous, _ = self._signal_indexes()
        sto_now = float(self.indicator.sto[current])
        sto_prev = float(self.indicator.sto[previous])
        return sto_prev <= 50.0 and sto_now > 50.0, sto_prev >= 50.0 and sto_now < 50.0

    def _twist_signals(self):
        current, previous, older = self._signal_indexes()
        sto_now = float(self.indicator.sto[current])
        sto_prev = float(self.indicator.sto[previous])
        sto_older = float(self.indicator.sto[older])
        return sto_prev < sto_older and sto_now > sto_prev, sto_prev > sto_older and sto_now < sto_prev

    def _cloud_twist_signals(self):
        current, previous, _ = self._signal_indexes()
        sto_now = float(self.indicator.sto[current])
        sto_prev = float(self.indicator.sto[previous])
        signal_now = float(self.indicator.signal[current])
        signal_prev = float(self.indicator.signal[previous])
        return sto_prev <= signal_prev and sto_now > signal_now, sto_prev >= signal_prev and sto_now < signal_now

    def _get_signals(self):
        mode = str(self.p.mode)
        if mode == 'breakdown':
            return self._breakdown_signals()
        if mode == 'cloudtwist':
            return self._cloud_twist_signals()
        return self._twist_signals()

    def _reset_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None

    def _open_long(self):
        self.pending_entry_direction = 1
        self.buy(size=self.p.lot)

    def _open_short(self):
        self.pending_entry_direction = -1
        self.sell(size=self.p.lot)

    def _close_position(self):
        self.close()
        self._reset_levels()

    def _manage_protective_levels(self):
        if not self.position or self.entry_price is None:
            return False

        low = float(self.data.low[0])
        high = float(self.data.high[0])

        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self._close_position()
                return True
            if self.target_price is not None and high >= self.target_price:
                self._close_position()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self._close_position()
                return True
            if self.target_price is not None and low <= self.target_price:
                self._close_position()
                return True

        return False

    def next(self):
        if len(self.data) < self.warmup:
            return

        if self._manage_protective_levels():
            return

        buy_signal, sell_signal = self._get_signals()

        if buy_signal:
            self.buy_signal_count += 1
        if sell_signal:
            self.sell_signal_count += 1

        if self.position:
            if self.position.size > 0 and sell_signal:
                self._close_position()
                self._open_short()
                return
            if self.position.size < 0 and buy_signal:
                self._close_position()
                self._open_long()
                return
        else:
            if buy_signal:
                self._open_long()
                return
            if sell_signal:
                self._open_short()
                return

    def notify_order(self, order):
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.pending_entry_direction = 0
            return

        if order.status != order.Completed:
            return

        self.completed_order_count += 1

        if self.pending_entry_direction == 1 and order.isbuy():
            self.buy_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return

        if self.pending_entry_direction == -1 and order.issell():
            self.sell_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return

        if not self.position:
            self._reset_levels()

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
