from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import random

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


class PokerShowStrategy(bt.Strategy):
    params = dict(
        lot=0.10,
        stop_loss_pips=50,
        take_profit_pips=150,
        use_buy=True,
        use_sell=True,
        ma_distance_points=50,
        ma_period=24,
        ma_shift=0,
        ma_method='ema',
        applied_price='close',
        reverse_signal=False,
        poker_threshold=16383,
        rng_seed=42,
        point=0.01,
    )

    def __init__(self):
        self.base_feed = self.datas[0]
        self.signal_feed = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.order = None
        self.pending_action = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_base_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.rng = random.Random(int(self.p.rng_seed))
        price_line = self._select_price_line(self.signal_feed, self.p.applied_price)
        self.ma_signal = self._build_ma(price_line, self.p.ma_method, self.p.ma_period)

    def log(self, text):
        dt = bt.num2date(self.base_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        dt = bt.num2date(self.base_feed.datetime[0])
        if self.last_base_dt == dt:
            return
        self.last_base_dt = dt
        self.bar_num += 1

        if self.order is not None:
            return
        if len(self.signal_feed) < max(int(self.p.ma_period) + 2, 3):
            return

        if self.position:
            self._check_exit_levels()
            return

        ma_ago = max(int(self.p.ma_shift), 0) + 1
        ma_value = self._line_value(self.ma_signal, ma_ago)
        close_0 = float(self.base_feed.close[0])
        if ma_value is None:
            return

        distance = float(self.p.ma_distance_points) * float(self.p.point)
        buy_condition = (ma_value > close_0 + distance) if not self.p.reverse_signal else (ma_value < close_0 - distance)
        sell_condition = (ma_value < close_0 - distance) if not self.p.reverse_signal else (ma_value > close_0 + distance)

        if self.p.use_buy and self.rng.randint(0, 32767) < int(self.p.poker_threshold) and buy_condition:
            self.pending_action = 'open_long'
            self.order = self.buy(size=float(self.p.lot))
            self.log(f'OPEN LONG lot={self.p.lot:.2f} ma={ma_value:.5f} close={close_0:.5f}')
            return

        if self.p.use_sell and self.rng.randint(0, 32767) < int(self.p.poker_threshold) and sell_condition:
            self.pending_action = 'open_short'
            self.order = self.sell(size=float(self.p.lot))
            self.log(f'OPEN SHORT lot={self.p.lot:.2f} ma={ma_value:.5f} close={close_0:.5f}')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if order.status == bt.Order.Completed:
            if self.pending_action == 'open_long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self.entry_price = float(order.executed.price)
                self.stop_price = self.entry_price - float(self.p.stop_loss_pips) * float(self.p.point) if self.p.stop_loss_pips else None
                self.take_profit_price = self.entry_price + float(self.p.take_profit_pips) * float(self.p.point) if self.p.take_profit_pips else None
            elif self.pending_action == 'open_short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self.entry_price = float(order.executed.price)
                self.stop_price = self.entry_price + float(self.p.stop_loss_pips) * float(self.p.point) if self.p.stop_loss_pips else None
                self.take_profit_price = self.entry_price - float(self.p.take_profit_pips) * float(self.p.point) if self.p.take_profit_pips else None
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
        high_0 = float(self.base_feed.high[0])
        low_0 = float(self.base_feed.low[0])
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

    def _clear_trade_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    @staticmethod
    def _line_value(line, ago=0):
        value = float(line[-ago] if ago else line[0])
        if not math.isfinite(value):
            return None
        return value

    @staticmethod
    def _select_price_line(data, applied_price):
        value = str(applied_price).lower()
        if value == 'open':
            return data.open
        if value == 'high':
            return data.high
        if value == 'low':
            return data.low
        if value == 'median':
            return (data.high + data.low) / 2.0
        if value == 'typical':
            return (data.high + data.low + data.close) / 3.0
        if value == 'weighted':
            return (data.high + data.low + data.close + data.close) / 4.0
        return data.close

    @staticmethod
    def _build_ma(line, method, period):
        method_name = str(method).lower()
        if method_name == 'sma':
            return bt.indicators.SimpleMovingAverage(line, period=period)
        if method_name == 'smma':
            return bt.indicators.SmoothedMovingAverage(line, period=period)
        if method_name == 'wma':
            return bt.indicators.WeightedMovingAverage(line, period=period)
        return bt.indicators.ExponentialMovingAverage(line, period=period)
