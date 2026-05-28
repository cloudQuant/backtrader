from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
    })
    if '<VOL>' in df.columns:
        df['openinterest'] = df['<VOL>']
    else:
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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


def applied_price(data, mode):
    mode = str(mode).upper()
    if mode == 'PRICE_OPEN':
        return data.open
    if mode == 'PRICE_HIGH':
        return data.high
    if mode == 'PRICE_LOW':
        return data.low
    if mode == 'PRICE_MEDIAN':
        return (data.high + data.low) / 2.0
    if mode == 'PRICE_TYPICAL':
        return (data.high + data.low + data.close) / 3.0
    if mode == 'PRICE_WEIGHTED':
        return (data.high + data.low + 2.0 * data.close) / 4.0
    return data.close


def ma_indicator(source, period, method):
    method = str(method).upper()
    if method == 'MODE_EMA':
        return bt.indicators.ExponentialMovingAverage(source, period=period)
    if method == 'MODE_SMMA':
        return bt.indicators.SmoothedMovingAverage(source, period=period)
    if method == 'MODE_LWMA':
        return bt.indicators.WeightedMovingAverage(source, period=period)
    return bt.indicators.SimpleMovingAverage(source, period=period)


class FiveEightMACrossStrategy(bt.Strategy):
    params = dict(
        lot=0.1,
        stop_loss_pips=0,
        take_profit_pips=40,
        trailing_stop_pips=0,
        point=0.01,
        price_digits=2,
        ma_fast_period=5,
        ma_fast_shift=-1,
        ma_fast_method='MODE_EMA',
        ma_fast_price='PRICE_CLOSE',
        ma_slow_period=8,
        ma_slow_shift=0,
        ma_slow_method='MODE_EMA',
        ma_slow_price='PRICE_OPEN',
    )

    def __init__(self):
        self.fast_ma = ma_indicator(applied_price(self.data, self.p.ma_fast_price), self.p.ma_fast_period, self.p.ma_fast_method)
        self.slow_ma = ma_indicator(applied_price(self.data, self.p.ma_slow_price), self.p.ma_slow_period, self.p.ma_slow_method)
        self.order = None
        self.deferred_signal = 0
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _line_value(self, line, bars_ago, shift):
        logical_bars_ago = bars_ago + int(shift)
        if logical_bars_ago < 0:
            logical_bars_ago = 0
        index = -logical_bars_ago if logical_bars_ago else 0
        return float(line[index])

    def _sync_position_state(self):
        if not self.position:
            self._entry_price = None
            self._stop_price = None
            self._take_profit_price = None
            self._last_position_size = 0.0
            return
        if self._entry_price is not None and self._last_position_size == float(self.position.size):
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        stop_distance = float(self.p.stop_loss_pips) * pip_size
        take_distance = float(self.p.take_profit_pips) * pip_size
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price + take_distance if take_distance > 0 else None
        else:
            self._stop_price = self._entry_price + stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price - take_distance if take_distance > 0 else None

    def _manage_trailing_stop(self):
        if not self.position:
            return
        pip_size = self._pip_size()
        trailing_distance = float(self.p.trailing_stop_pips) * pip_size
        if trailing_distance <= 0:
            return
        close = float(self.data.close[0])
        if self.position.size > 0:
            candidate = close - trailing_distance
            if self._stop_price is None or candidate > self._stop_price:
                self._stop_price = candidate
        else:
            candidate = close + trailing_distance
            if self._stop_price is None or candidate < self._stop_price:
                self._stop_price = candidate

    def _manage_protective_exit(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.log(f'long protective exit stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.log(f'long protective exit tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.log(f'short protective exit stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.log(f'short protective exit tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        return False

    def _signal(self):
        fast1 = self._line_value(self.fast_ma, 1, self.p.ma_fast_shift)
        fast2 = self._line_value(self.fast_ma, 2, self.p.ma_fast_shift)
        slow1 = self._line_value(self.slow_ma, 1, self.p.ma_slow_shift)
        slow2 = self._line_value(self.slow_ma, 2, self.p.ma_slow_shift)
        if fast1 > slow1 and fast2 < slow2:
            return 1
        if fast1 < slow1 and fast2 > slow2:
            return -1
        return 0

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.ma_fast_period) + abs(int(self.p.ma_fast_shift)), int(self.p.ma_slow_period) + abs(int(self.p.ma_slow_shift))) + 3
        if len(self.data) < warmup:
            return
        if self.order:
            return
        self._sync_position_state()
        if self.position:
            self._manage_trailing_stop()
            if self._manage_protective_exit():
                return
        if self.deferred_signal:
            signal = self.deferred_signal
            self.deferred_signal = 0
        else:
            signal = self._signal()
        if signal == 0:
            return
        self.signal_count += 1
        if signal > 0:
            if self.position.size < 0:
                self.deferred_signal = 1
                self.log('bullish cross: close short first')
                self.order = self.close()
                return
            if not self.position:
                self.log('bullish cross: open long')
                self.order = self.buy(size=self.p.lot)
                return
        if signal < 0:
            if self.position.size > 0:
                self.deferred_signal = -1
                self.log('bearish cross: close long first')
                self.order = self.close()
                return
            if not self.position:
                self.log('bearish cross: open short')
                self.order = self.sell(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            self._sync_position_state()
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
