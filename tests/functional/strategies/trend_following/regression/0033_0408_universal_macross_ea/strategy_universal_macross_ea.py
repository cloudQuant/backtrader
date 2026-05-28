from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    keep_cols = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']
    if 'spread' in df.columns:
        keep_cols.append('spread')
    df = df[keep_cols]
    if 'spread' not in df.columns:
        df['spread'] = 0
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class UniversalMACrossEAStrategy(bt.Strategy):
    params = dict(
        stop_loss_pips=100,
        take_profit_pips=200,
        trailing_stop_pips=40,
        trailing_step_pips=5,
        fast_ma_period=10,
        fast_ma_type='ema',
        fast_ma_price='close',
        slow_ma_period=80,
        slow_ma_type='ema',
        slow_ma_price='close',
        min_cross_distance_pips=0,
        reverse_condition=False,
        confirmed_on_entry=True,
        one_entry_per_bar=True,
        stop_and_reverse=True,
        pure_sar=False,
        use_hour_trade=False,
        start_hour=10,
        end_hour=11,
        lot=0.10,
        point=0.01,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.fast_ma = bt.indicators.ExponentialMovingAverage(self.data0.close, period=self.p.fast_ma_period)
        self.slow_ma = bt.indicators.ExponentialMovingAverage(self.data0.close, period=self.p.slow_ma_period)
        self.order = None
        self.pending_action = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_trade = ''
        self.check_time = None
        self.check_entry_time = None
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        if len(self.data0) < max(100, self.p.slow_ma_period + 5):
            return
        if self.order is not None:
            return

        dt = bt.num2date(self.data0.datetime[0])
        if self.p.use_hour_trade:
            if not (int(self.p.start_hour) <= dt.hour <= int(self.p.end_hour)):
                return

        self._check_exit_levels()
        self._apply_trailing()
        if self.order is not None:
            return

        if self.p.confirmed_on_entry:
            if self.check_time == dt:
                return
            self.check_time = dt
            fast_prev = self._finite(self.fast_ma[-2])
            fast_cur = self._finite(self.fast_ma[-1])
            slow_prev = self._finite(self.slow_ma[-2])
            slow_cur = self._finite(self.slow_ma[-1])
        else:
            fast_prev = self._finite(self.fast_ma[-1])
            fast_cur = self._finite(self.fast_ma[0])
            slow_prev = self._finite(self.slow_ma[-1])
            slow_cur = self._finite(self.slow_ma[0])
        if None in (fast_prev, fast_cur, slow_prev, slow_cur):
            return

        min_cross_distance = self._distance(self.p.min_cross_distance_pips)
        if not self.p.reverse_condition:
            buy_condition = fast_prev < slow_prev and fast_cur > slow_cur and (fast_cur - slow_cur) >= min_cross_distance
            sell_condition = fast_prev > slow_prev and fast_cur < slow_cur and (slow_cur - fast_cur) >= min_cross_distance
        else:
            sell_condition = fast_prev < slow_prev and fast_cur > slow_cur and (fast_cur - slow_cur) >= min_cross_distance
            buy_condition = fast_prev > slow_prev and fast_cur < slow_cur and (slow_cur - fast_cur) >= min_cross_distance

        if self.p.stop_and_reverse and self.position:
            if (self.last_trade == 'BUY' and sell_condition) or (self.last_trade == 'SELL' and buy_condition):
                self.pending_action = 'close'
                self.order = self.close()
                self.log('STOP AND REVERSE close current position')
                return

        if self.position:
            return

        if self.p.one_entry_per_bar:
            if self.check_entry_time == dt:
                return
            self.check_entry_time = dt

        if buy_condition:
            self.pending_action = 'open_long'
            self.order = self.buy(size=float(self.p.lot))
            self._prepare_entry_levels('long', float(self.data0.close[0]))
            self.log(f'OPEN LONG fast_prev={fast_prev:.5f} fast_cur={fast_cur:.5f} slow_prev={slow_prev:.5f} slow_cur={slow_cur:.5f}')
            return
        if sell_condition:
            self.pending_action = 'open_short'
            self.order = self.sell(size=float(self.p.lot))
            self._prepare_entry_levels('short', float(self.data0.close[0]))
            self.log(f'OPEN SHORT fast_prev={fast_prev:.5f} fast_cur={fast_cur:.5f} slow_prev={slow_prev:.5f} slow_cur={slow_cur:.5f}')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.pending_action == 'open_long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self.last_trade = 'BUY'
                self.entry_price = float(order.executed.price)
                self._prepare_entry_levels('long', self.entry_price)
            elif self.pending_action == 'open_short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self.last_trade = 'SELL'
                self.entry_price = float(order.executed.price)
                self._prepare_entry_levels('short', self.entry_price)
            elif self.pending_action == 'close' and not self.position:
                self._clear_trade_levels()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            if order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            self.pending_action = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f}')
        if not self.position:
            self._clear_trade_levels()

    def _check_exit_levels(self):
        if self.p.pure_sar:
            return False
        high_0 = float(self.data0.high[0])
        low_0 = float(self.data0.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low_0 <= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and high_0 >= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG take_profit={self.take_profit_price:.5f}')
                return True
            return False
        if self.position.size < 0:
            if self.stop_price is not None and high_0 >= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE SHORT stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and low_0 <= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE SHORT take_profit={self.take_profit_price:.5f}')
                return True
        return False

    def _apply_trailing(self):
        if self.p.pure_sar or not self.position or self.order is not None:
            return
        if float(self.p.trailing_stop_pips) <= 0:
            return
        current_price = float(self.data0.close[0])
        trigger = self._distance(self.p.trailing_stop_pips) + self._distance(self.p.trailing_step_pips)
        if self.position.size > 0:
            if current_price - self.entry_price > trigger:
                candidate = current_price - self._distance(self.p.trailing_stop_pips)
                if self.stop_price is None or self.stop_price < current_price - trigger:
                    self.stop_price = candidate
                elif candidate > self.stop_price:
                    self.stop_price = candidate
            return
        if self.entry_price - current_price > trigger:
            candidate = current_price + self._distance(self.p.trailing_stop_pips)
            if self.stop_price is None or self.stop_price == 0:
                self.stop_price = candidate
            elif candidate < self.stop_price:
                self.stop_price = candidate

    def _prepare_entry_levels(self, side, reference_price):
        self.entry_price = float(reference_price)
        if self.p.pure_sar:
            self.stop_price = None
            self.take_profit_price = None
            return
        if side == 'long':
            self.stop_price = self.entry_price - self._distance(self.p.stop_loss_pips) if self.p.stop_loss_pips else None
            self.take_profit_price = self.entry_price + self._distance(self.p.take_profit_pips) if self.p.take_profit_pips else None
        else:
            self.stop_price = self.entry_price + self._distance(self.p.stop_loss_pips) if self.p.stop_loss_pips else None
            self.take_profit_price = self.entry_price - self._distance(self.p.take_profit_pips) if self.p.take_profit_pips else None

    def _clear_trade_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    @staticmethod
    def _finite(value):
        value = float(value)
        if not math.isfinite(value):
            return None
        return value

    def _distance(self, pips):
        return float(pips) * float(self.p.point)
