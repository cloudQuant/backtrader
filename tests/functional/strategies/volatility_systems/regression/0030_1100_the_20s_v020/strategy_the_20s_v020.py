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


class The20sV020Signal(Indicator):
    lines = ('sell', 'buy')
    params = dict(
        alg='MODE_1',
        level=100,
        ratio=0.2,
        direct=False,
        atr_period=15,
        point=0.01,
    )

    def __init__(self):
        self.atr = btind.ATR(self.data, period=max(int(self.p.atr_period), 1))
        self.addminperiod(max(int(self.p.atr_period), 5) + 6)

    def next(self):
        self.lines.buy[0] = 0.0
        self.lines.sell[0] = 0.0

        if len(self.data) < 6:
            return

        dlevel = float(self.p.level) * float(self.p.point)
        last_range = float(self.data.high[-1]) - float(self.data.low[-1])
        top20 = float(self.data.high[-1]) - last_range * float(self.p.ratio)
        bottom20 = float(self.data.low[-1]) + last_range * float(self.p.ratio)
        atr = float(self.atr[0])

        raw_buy = 0.0
        raw_sell = 0.0

        if str(self.p.alg) == 'MODE_1':
            if float(self.data.open[-1]) >= top20 and float(self.data.close[-1]) <= bottom20 and float(self.data.low[0]) <= float(self.data.low[-1]) - dlevel:
                raw_buy = float(self.data.low[0]) - atr * 3.0 / 8.0
            elif float(self.data.open[-1]) <= bottom20 and float(self.data.close[-1]) >= top20 and float(self.data.high[0]) >= float(self.data.high[-1]) + dlevel:
                raw_sell = float(self.data.high[0]) + atr * 3.0 / 8.0
        else:
            cond = (
                (float(self.data.high[-4]) - float(self.data.low[-4]) > last_range)
                and (float(self.data.high[-3]) - float(self.data.low[-3]) > last_range)
                and (float(self.data.high[-2]) - float(self.data.low[-2]) > last_range)
                and float(self.data.high[-2]) > float(self.data.high[-1])
                and float(self.data.low[-2]) < float(self.data.low[-1])
            )
            if cond:
                if float(self.data.open[0]) <= bottom20:
                    raw_buy = float(self.data.low[0]) - atr * 3.0 / 8.0
                if float(self.data.open[0]) >= top20:
                    raw_sell = float(self.data.high[0]) + atr * 3.0 / 8.0

        if bool(self.p.direct):
            self.lines.buy[0] = raw_buy
            self.lines.sell[0] = raw_sell
        else:
            self.lines.buy[0] = raw_sell
            self.lines.sell[0] = raw_buy


class The20sV020Strategy(Strategy):
    params = dict(
        alg='MODE_1',
        level=100,
        ratio=0.2,
        direct=False,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
    )

    def __init__(self):
        self.indicator = The20sV020Signal(
            self.data,
            alg=self.p.alg,
            level=self.p.level,
            ratio=self.p.ratio,
            direct=self.p.direct,
            point=self.p.point,
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
        self.warmup = 25

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
        if len(self.data) < self.warmup:
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
