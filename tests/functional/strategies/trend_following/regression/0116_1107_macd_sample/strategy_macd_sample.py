from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import backtrader.feeds as btfeeds
import backtrader.indicators as btind
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


class MacdSampleStrategy(Strategy):
    params = dict(
        lots=0.1,
        take_profit_pips=50,
        trailing_stop_pips=30,
        macd_open_level_pips=3,
        macd_close_level_pips=2,
        ma_trend_period=26,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.macd = btind.MACD(self.data.close, period_me1=12, period_me2=26, period_signal=9)
        self.ema = btind.ExponentialMovingAverage(self.data.close, period=self.p.ma_trend_period)
        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.close_long_signal_count = 0
        self.close_short_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.entry_price = None
        self.take_profit_price = None
        self.trailing_stop_price = None
        self.pending_entry_direction = 0
        self.warmup = max(self.p.ma_trend_period + 5, 35)

    def log(self, text):
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _adjusted_point(self):
        return self.p.point * (10 if self.p.price_digits in (3, 5) else 1)

    def _take_profit_distance(self):
        return self.p.take_profit_pips * self._adjusted_point()

    def _trailing_distance(self):
        return self.p.trailing_stop_pips * self._adjusted_point()

    def _open_level(self):
        return self.p.macd_open_level_pips * self._adjusted_point()

    def _close_level(self):
        return self.p.macd_close_level_pips * self._adjusted_point()

    def _reset_levels(self):
        self.entry_price = None
        self.take_profit_price = None
        self.trailing_stop_price = None

    def _open_long(self):
        self.pending_entry_direction = 1
        self.buy(size=self.p.lots)

    def _open_short(self):
        self.pending_entry_direction = -1
        self.sell(size=self.p.lots)

    def _close_position(self, reason):
        self.log(reason)
        self.close()

    def _update_trailing_levels(self):
        if not self.position or self.entry_price is None or self.p.trailing_stop_pips <= 0:
            return

        trailing_distance = self._trailing_distance()
        if self.position.size > 0:
            if float(self.data.high[0]) - self.entry_price > trailing_distance:
                candidate = float(self.data.close[0]) - trailing_distance
                if self.trailing_stop_price is None or candidate > self.trailing_stop_price:
                    self.trailing_stop_price = round(candidate, self.p.price_digits)
        else:
            if self.entry_price - float(self.data.low[0]) > trailing_distance:
                candidate = float(self.data.close[0]) + trailing_distance
                if self.trailing_stop_price is None or candidate < self.trailing_stop_price:
                    self.trailing_stop_price = round(candidate, self.p.price_digits)

    def _manage_exit_orders(self):
        if not self.position or self.entry_price is None:
            return False

        high = float(self.data.high[0])
        low = float(self.data.low[0])
        self._update_trailing_levels()

        if self.position.size > 0:
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self._close_position(f'close long take_profit={self.take_profit_price:.2f}')
                return True
            if self.trailing_stop_price is not None and low <= self.trailing_stop_price:
                self._close_position(f'close long trailing={self.trailing_stop_price:.2f}')
                return True
        else:
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self._close_position(f'close short take_profit={self.take_profit_price:.2f}')
                return True
            if self.trailing_stop_price is not None and high >= self.trailing_stop_price:
                self._close_position(f'close short trailing={self.trailing_stop_price:.2f}')
                return True

        return False

    def _long_open_signal(self):
        macd_now = float(self.macd.macd[0])
        macd_prev = float(self.macd.macd[-1])
        signal_now = float(self.macd.signal[0])
        signal_prev = float(self.macd.signal[-1])
        ema_now = float(self.ema[0])
        ema_prev = float(self.ema[-1])
        return (
            macd_now < 0.0
            and macd_now > signal_now
            and macd_prev < signal_prev
            and abs(macd_now) > self._open_level()
            and ema_now > ema_prev
        )

    def _short_open_signal(self):
        macd_now = float(self.macd.macd[0])
        macd_prev = float(self.macd.macd[-1])
        signal_now = float(self.macd.signal[0])
        signal_prev = float(self.macd.signal[-1])
        ema_now = float(self.ema[0])
        ema_prev = float(self.ema[-1])
        return (
            macd_now > 0.0
            and macd_now < signal_now
            and macd_prev > signal_prev
            and macd_now > self._open_level()
            and ema_now < ema_prev
        )

    def _long_close_signal(self):
        macd_now = float(self.macd.macd[0])
        macd_prev = float(self.macd.macd[-1])
        signal_now = float(self.macd.signal[0])
        signal_prev = float(self.macd.signal[-1])
        return (
            macd_now > 0.0
            and macd_now < signal_now
            and macd_prev > signal_prev
            and macd_now > self._close_level()
        )

    def _short_close_signal(self):
        macd_now = float(self.macd.macd[0])
        macd_prev = float(self.macd.macd[-1])
        signal_now = float(self.macd.signal[0])
        signal_prev = float(self.macd.signal[-1])
        return (
            macd_now < 0.0
            and macd_now > signal_now
            and macd_prev < signal_prev
            and abs(macd_now) > self._close_level()
        )

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.warmup:
            return

        if self._manage_exit_orders():
            return

        long_open = self._long_open_signal()
        short_open = self._short_open_signal()
        long_close = self._long_close_signal()
        short_close = self._short_close_signal()

        if long_open:
            self.buy_signal_count += 1
        if short_open:
            self.sell_signal_count += 1
        if long_close:
            self.close_long_signal_count += 1
        if short_close:
            self.close_short_signal_count += 1

        if self.position:
            if self.position.size > 0 and long_close:
                self._close_position('close long macd reversal')
                return
            if self.position.size < 0 and short_close:
                self._close_position('close short macd reversal')
                return
            return

        if long_open:
            self.log('buy macd bullish cross below zero with ema uptrend')
            self._open_long()
            return
        if short_open:
            self.log('sell macd bearish cross above zero with ema downtrend')
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
            self.take_profit_price = round(self.entry_price + self._take_profit_distance(), self.p.price_digits)
            self.trailing_stop_price = None
            self.pending_entry_direction = 0
            return

        if self.pending_entry_direction == -1 and order.issell():
            self.sell_count += 1
            self.entry_price = order.executed.price
            self.take_profit_price = round(self.entry_price - self._take_profit_distance(), self.p.price_digits)
            self.trailing_stop_price = None
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
        self._reset_levels()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
