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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class LarryConnersRsi2Strategy(bt.Strategy):
    params = dict(
        lot=1.0,
        short_sma_periods=5,
        long_sma_periods=200,
        rsi_periods=2,
        rsi_long_entry=6,
        rsi_short_entry=95,
        use_stop_loss=True,
        stop_loss_pips=30,
        use_take_profit=True,
        take_profit_pips=60,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.short_sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.short_sma_periods)
        self.long_sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.long_sma_periods)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_periods)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def _pip_size(self):
        digits_adjust = 10 if self.p.price_digits in (3, 5, 1) else 1
        return self.p.point * digits_adjust

    def _clear_position_state(self):
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        self._position_was_open = False

    def _set_initial_protection(self):
        if not self.position:
            self._clear_position_state()
            return
        if self._entry_price is not None and self._last_position_size == self.position.size:
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        stop_distance = self.p.stop_loss_pips * pip_size
        take_distance = self.p.take_profit_pips * pip_size
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if self.p.use_stop_loss else None
            self._take_profit_price = self._entry_price + take_distance if self.p.use_take_profit else None
        else:
            self._stop_price = self._entry_price + stop_distance if self.p.use_stop_loss else None
            self._take_profit_price = self._entry_price - take_distance if self.p.use_take_profit else None

    def _maybe_hit_protection(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        warmup = self.p.long_sma_periods + 5
        if len(self.data) < warmup:
            return
        if self.order:
            return

        close_prev = float(self.data.close[-1])
        short_sma_prev = float(self.short_sma[-1])
        long_sma_prev = float(self.long_sma[-1])
        rsi_prev = float(self.rsi[-1])

        self._set_initial_protection()

        if self.position:
            if self._maybe_hit_protection():
                return
            if self.position.size > 0 and close_prev > short_sma_prev:
                self.order = self.close()
                return
            if self.position.size < 0 and close_prev < short_sma_prev:
                self.order = self.close()
                return
            return

        if rsi_prev < self.p.rsi_long_entry and close_prev > long_sma_prev:
            self.order = self.buy(size=self.p.lot)
            return

        if rsi_prev > self.p.rsi_short_entry and close_prev < long_sma_prev:
            self.order = self.sell(size=self.p.lot)
            return

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed and self.position:
            self._set_initial_protection()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None
        if not self.position:
            self._clear_position_state()

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._clear_position_state()
