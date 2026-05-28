from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader.feeds as btfeeds
from backtrader.indicator import Indicator
from backtrader.strategy import Strategy
from backtrader.utils.dateintern import num2date
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


def _weighted_ma(values):
    weights = list(range(1, len(values) + 1))
    denominator = float(sum(weights))
    return sum(value * weight for value, weight in zip(values, weights)) / denominator


class ColorHMA(Indicator):
    lines = ('hma', 'direction')
    params = dict(period=13)

    def __init__(self):
        self.period = max(int(self.p.period), 2)
        self.half_period = max(int(math.floor(self.period / 2.0)), 1)
        self.sqrt_period = max(int(math.floor(math.sqrt(self.period))), 1)
        self._dma_history = []
        self.addminperiod(self.period + self.sqrt_period + 2)

    def _window(self, length):
        return [float(self.data[-idx]) for idx in range(length - 1, -1, -1)]

    def next(self):
        if len(self.data) < self.period:
            current = float(self.data.close[0]) if hasattr(self.data, 'close') else float(self.data[0])
            self._dma_history.append(current)
            self.l.hma[0] = current
            self.l.direction[0] = 0.0
            return

        half_values = self._window(self.half_period)
        full_values = self._window(self.period)
        lwma_half = _weighted_ma(half_values)
        lwma_full = _weighted_ma(full_values)
        dma = 2.0 * lwma_half - lwma_full
        self._dma_history.append(dma)

        if len(self._dma_history) >= self.sqrt_period:
            hma = _weighted_ma(self._dma_history[-self.sqrt_period:])
        else:
            hma = dma

        self.l.hma[0] = hma
        if len(self) < 2:
            self.l.direction[0] = 0.0
        elif self.l.hma[-1] < self.l.hma[0]:
            self.l.direction[0] = 1.0
        elif self.l.hma[-1] > self.l.hma[0]:
            self.l.direction[0] = -1.0
        else:
            self.l.direction[0] = self.l.direction[-1]


class ColorHMAStrategy(Strategy):
    params = dict(
        signal_bar=1,
        hma_period=13,
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
    )

    def __init__(self):
        self.indicator = ColorHMA(self.data, period=self.p.hma_period)
        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.pending_entry_direction = 0
        self.warmup = max(int(self.p.hma_period) + int(math.sqrt(max(self.p.hma_period, 1))) + max(int(self.p.signal_bar), 1) + 5, 30)

    def log(self, text):
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _get_signals(self):
        shift = max(int(self.p.signal_bar), 1)
        v0 = float(self.indicator.hma[-shift])
        v1 = float(self.indicator.hma[-(shift + 1)])
        v2 = float(self.indicator.hma[-(shift + 2)])
        buy_open = self.p.buy_pos_open and v1 < v2 and v0 > v1
        sell_open = self.p.sell_pos_open and v1 > v2 and v0 < v1
        buy_close = self.p.buy_pos_close and sell_open
        sell_close = self.p.sell_pos_close and buy_open
        return buy_open, sell_open, buy_close, sell_close

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

    def _close_long(self, reason):
        self.log(reason)
        self.close()
        self._reset_levels()

    def _close_short(self, reason):
        self.log(reason)
        self.close()
        self._reset_levels()

    def _manage_protective_levels(self):
        if not self.position or self.entry_price is None:
            return False
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self._close_long(f'close long stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and high >= self.target_price:
                self._close_long(f'close long target={self.target_price:.2f}')
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self._close_short(f'close short stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and low <= self.target_price:
                self._close_short(f'close short target={self.target_price:.2f}')
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.warmup:
            return
        if self._manage_protective_levels():
            return

        buy_open, sell_open, buy_close, sell_close = self._get_signals()
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1

        if self.position:
            if self.position.size > 0:
                if buy_close:
                    self._close_long('close long on ColorHMA downward reversal')
                    if sell_open:
                        self._open_short()
                    return
            else:
                if sell_close:
                    self._close_short('close short on ColorHMA upward reversal')
                    if buy_open:
                        self._open_long()
                    return
        else:
            if buy_open:
                self.log('buy on ColorHMA upward reversal')
                self._open_long()
                return
            if sell_open:
                self.log('sell on ColorHMA downward reversal')
                self._open_short()
                return

    def notify_order(self, order):
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.pending_entry_direction = 0
            self.log(f'order {order.getstatusname()}')
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
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
