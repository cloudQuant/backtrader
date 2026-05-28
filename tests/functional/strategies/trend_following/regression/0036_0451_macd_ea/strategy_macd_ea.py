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
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class MacdEaStrategy(bt.Strategy):
    params = dict(
        lot=1.0,
        stop_loss_pips=80,
        take_profit_pips=500,
        profit_one_pips=70,
        breakeven_pips=0,
        ma_fast_period=55,
        ma_fast_method='ema',
        ma_slow_period=69,
        ma_slow_method='sma',
        ma_filter_period=2,
        ma_filter_method='wma',
        macd_fast_period=120,
        macd_slow_period=260,
        macd_signal_period=90,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        ma_fast_cls = bt.ind.ExponentialMovingAverage if str(self.p.ma_fast_method).lower() == 'ema' else bt.ind.SimpleMovingAverage
        ma_slow_cls = bt.ind.ExponentialMovingAverage if str(self.p.ma_slow_method).lower() == 'ema' else bt.ind.SimpleMovingAverage
        ma_filter_cls = bt.ind.WeightedMovingAverage if str(self.p.ma_filter_method).lower() == 'wma' else bt.ind.SimpleMovingAverage
        self.ma_fast = ma_fast_cls(self.data.close, period=self.p.ma_fast_period)
        self.ma_slow = ma_slow_cls(self.data.close, period=self.p.ma_slow_period)
        self.ma_filter = ma_filter_cls(self.data.close, period=self.p.ma_filter_period)
        self.macd = bt.ind.MACD(
            self.data.close,
            period_me1=self.p.macd_fast_period,
            period_me2=self.p.macd_slow_period,
            period_signal=self.p.macd_signal_period,
        )
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._partial_taken = False
        self._last_position_size = 0.0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        digits_adjust = 10 if self.p.price_digits in (3, 5) else 1
        return self.p.point * digits_adjust

    def _clear_position_state(self):
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._partial_taken = False
        self._last_position_size = 0.0

    def _set_initial_protection(self):
        if not self.position:
            self._clear_position_state()
            return
        if self._entry_price is not None and self._last_position_size == float(self.position.size):
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        stop_distance = self.p.stop_loss_pips * pip_size
        take_distance = self.p.take_profit_pips * pip_size
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if self.p.stop_loss_pips > 0 else None
            self._take_profit_price = self._entry_price + take_distance if self.p.take_profit_pips > 0 else None
        else:
            self._stop_price = self._entry_price + stop_distance if self.p.stop_loss_pips > 0 else None
            self._take_profit_price = self._entry_price - take_distance if self.p.take_profit_pips > 0 else None

    def _update_breakeven(self):
        if not self.position or self.p.breakeven_pips <= 0 or self._entry_price is None:
            return
        distance = self.p.breakeven_pips * self._pip_size()
        close = float(self.data.close[0])
        if self.position.size > 0:
            if close - self._entry_price > distance:
                if self._stop_price is None or self._stop_price < self._entry_price:
                    self._stop_price = self._entry_price
        else:
            if self._entry_price - close > distance:
                if self._stop_price is None or self._stop_price > self._entry_price:
                    self._stop_price = self._entry_price

    def _maybe_hit_exit(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.log(f'close long stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.log(f'close long take_profit={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.log(f'close short stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.log(f'close short take_profit={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        return False

    def _maybe_partial_close(self):
        if not self.position or self.p.profit_one_pips <= 0 or self._partial_taken or self._entry_price is None:
            return False
        distance = self.p.profit_one_pips * self._pip_size()
        close = float(self.data.close[0])
        if self.position.size > 0 and close > self._entry_price + distance:
            half_size = abs(float(self.position.size)) / 2.0
            if half_size > 0:
                self.log(f'close long partial size={half_size:.2f}')
                self.order = self.close(size=half_size)
                self._partial_taken = True
                return True
        if self.position.size < 0 and close < self._entry_price - distance:
            half_size = abs(float(self.position.size)) / 2.0
            if half_size > 0:
                self.log(f'close short partial size={half_size:.2f}')
                self.order = self.close(size=half_size)
                self._partial_taken = True
                return True
        return False

    def _macd_bull_cross(self):
        return float(self.macd.macd[-2]) > float(self.macd.signal[-2]) and float(self.macd.macd[-4]) < float(self.macd.signal[-4])

    def _macd_bear_cross(self):
        return float(self.macd.macd[-2]) < float(self.macd.signal[-2]) and float(self.macd.macd[-4]) > float(self.macd.signal[-4])

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.ma_slow_period, self.p.macd_slow_period + self.p.macd_signal_period) + 10
        if len(self.data) < warmup:
            return
        if self.order:
            return

        if self.position:
            self._set_initial_protection()
            self._update_breakeven()
            if self._maybe_hit_exit():
                return
            if self.position.size > 0 and self._macd_bear_cross():
                self.log('close long on opposite MACD cross')
                self.order = self.close()
                return
            if self.position.size < 0 and self._macd_bull_cross():
                self.log('close short on opposite MACD cross')
                self.order = self.close()
                return
            if self._maybe_partial_close():
                return
            return

        if self._macd_bull_cross():
            self.log(
                'buy '
                f'macd2={float(self.macd.macd[-2]):.4f} signal2={float(self.macd.signal[-2]):.4f} '
                f'macd4={float(self.macd.macd[-4]):.4f} signal4={float(self.macd.signal[-4]):.4f}'
            )
            self.order = self.buy(size=self.p.lot)
            return
        if self._macd_bear_cross():
            self.log(
                'sell '
                f'macd2={float(self.macd.macd[-2]):.4f} signal2={float(self.macd.signal[-2]):.4f} '
                f'macd4={float(self.macd.macd[-4]):.4f} signal4={float(self.macd.signal[-4]):.4f}'
            )
            self.order = self.sell(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and order.executed.size > 0 and self.position.size > 0:
                self.buy_count += 1
                self._set_initial_protection()
            elif order.issell() and order.executed.size < 0 and self.position.size < 0:
                self.sell_count += 1
                self._set_initial_protection()
            elif self.position:
                self._set_initial_protection()
            else:
                self._clear_position_state()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
        if not self.position:
            self._clear_position_state()
