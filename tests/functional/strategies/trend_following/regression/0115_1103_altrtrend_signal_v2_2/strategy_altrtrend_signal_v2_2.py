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


class AltrTrendSignalV22(Indicator):
    lines = ('sell', 'buy')
    params = dict(
        k=30,
        kstop=0.5,
        kperiod=150,
        per_adx=14,
    )

    def __init__(self):
        self.adx = btind.AverageDirectionalMovementIndex(self.data, period=max(int(self.p.per_adx), 1))
        self.addminperiod(max(int(self.p.per_adx), 1) + 2)
        self._trend = 0

    def next(self):
        self.lines.buy[0] = 0.0
        self.lines.sell[0] = 0.0

        adx_prev = float(self.adx[-1]) if len(self) > 1 else float(self.adx[0])
        if math.isnan(adx_prev) or adx_prev <= 0:
            return

        ssp = max(int(math.ceil(float(self.p.kperiod) / adx_prev)), 1)
        lookback = min(ssp, len(self.data))
        if lookback <= 0:
            return

        highs = []
        lows = []
        avg_range = 0.0
        for idx in range(lookback):
            high = float(self.data.high[-idx])
            low = float(self.data.low[-idx])
            highs.append(high)
            lows.append(low)
            avg_range += abs(high - low)

        trading_range = avg_range / (ssp + 1.0)
        ss_max = max(highs)
        ss_min = min(lows)
        threshold = (ss_max - ss_min) * float(self.p.k) / 100.0
        smin = ss_min + threshold
        smax = ss_max - threshold

        previous_trend = self._trend
        trend = previous_trend
        close = float(self.data.close[0])

        if close < smin:
            trend = -1
        if close > smax:
            trend = 1

        if previous_trend == 0:
            previous_trend = trend

        if trend != previous_trend and close > smax:
            self.lines.buy[0] = float(self.data.low[0]) - trading_range * float(self.p.kstop)
        if trend != previous_trend and close < smin:
            self.lines.sell[0] = float(self.data.high[0]) + trading_range * float(self.p.kstop)

        self._trend = trend if trend != 0 else previous_trend


class AltrTrendSignalV22Strategy(Strategy):
    params = dict(
        signal_bar=1,
        k=30,
        kstop=0.5,
        kperiod=150,
        per_adx=14,
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
    )

    def __init__(self):
        self.indicator = AltrTrendSignalV22(
            self.data,
            k=self.p.k,
            kstop=self.p.kstop,
            kperiod=self.p.kperiod,
            per_adx=self.p.per_adx,
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
        self.warmup = max(int(self.p.kperiod), int(self.p.per_adx) + 5)

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

    def _has_buy_signal(self):
        value = float(self.indicator.buy[-max(int(self.p.signal_bar), 1)])
        return not math.isnan(value) and value != 0.0

    def _has_sell_signal(self):
        value = float(self.indicator.sell[-max(int(self.p.signal_bar), 1)])
        return not math.isnan(value) and value != 0.0

    def next(self):
        if len(self.data) < self.warmup + max(int(self.p.signal_bar), 1):
            return

        if self._manage_protective_levels():
            return

        buy_signal = self._has_buy_signal()
        sell_signal = self._has_sell_signal()

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
