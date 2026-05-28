from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
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
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class WeightedPrice(bt.Indicator):
    lines = ('value',)

    def __init__(self):
        self.lines.value = (self.data.high + self.data.low + self.data.close * 2.0) / 4.0

    def next(self):
        self.lines.value[0] = (
            float(self.data.high[0]) + float(self.data.low[0]) + float(self.data.close[0]) * 2.0
        ) / 4.0

    def once(self, start, end):
        high_array = self.data.high.array
        low_array = self.data.low.array
        close_array = self.data.close.array
        value_line = self.lines.value.array
        while len(value_line) < end:
            value_line.append(float('nan'))

        actual_end = min(end, len(high_array), len(low_array), len(close_array))
        for i in range(start, actual_end):
            value_line[i] = (
                float(high_array[i]) + float(low_array[i]) + float(close_array[i]) * 2.0
            ) / 4.0


class EmaLwmaRsiStrategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        stop_loss_pips=150,
        take_profit_pips=150,
        ema_period=28,
        lwma_period=8,
        rsi_period=14,
        point_size=0.01,
        verbose=False,
    )

    def __init__(self):
        self.weighted_price = WeightedPrice(self.data)
        self.ma_ema = bt.indicators.ExponentialMovingAverage(self.weighted_price.value, period=self.p.ema_period)
        self.ma_lwma = bt.indicators.WeightedMovingAverage(self.weighted_price.value, period=self.p.lwma_period)
        self.rsi = bt.indicators.RSI(self.weighted_price.value, period=self.p.rsi_period)
        self.last_bar_dt = None
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.stop_price = None
        self.limit_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        if not self.p.verbose:
            return
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_bar(self):
        current = bt.num2date(self.data.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None
        self.stop_price = None
        self.limit_price = None

    def _place_exit_orders(self):
        if not self.position:
            return
        self._cancel_exit_orders()
        stop_distance = float(self.p.stop_loss_pips) * float(self.p.point_size)
        limit_distance = float(self.p.take_profit_pips) * float(self.p.point_size)
        size = abs(self.position.size)
        if self.position.size > 0:
            if stop_distance > 0:
                self.stop_price = self.position.price - stop_distance
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            if limit_distance > 0:
                self.limit_price = self.position.price + limit_distance
                self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=self.limit_price, oco=self.stop_order)
        else:
            if stop_distance > 0:
                self.stop_price = self.position.price + stop_distance
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price)
            if limit_distance > 0:
                self.limit_price = self.position.price - limit_distance
                self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=self.limit_price, oco=self.stop_order)

    def _build_signal(self):
        if len(self.ma_ema) < 2 or len(self.ma_lwma) < 2 or len(self.rsi) < 1:
            return None
        ema_now = float(self.ma_ema[0])
        ema_prev = float(self.ma_ema[-1])
        lwma_now = float(self.ma_lwma[0])
        lwma_prev = float(self.ma_lwma[-1])
        rsi_now = float(self.rsi[0])
        if ema_now < lwma_now and ema_prev > lwma_prev and rsi_now > 50.0:
            return 'buy'
        if ema_now > lwma_now and ema_prev < lwma_prev and rsi_now < 50.0:
            return 'sell'
        return None

    def next(self):
        self.bar_num += 1
        if not self._new_bar():
            return
        if self.entry_order is not None:
            return
        signal = self._build_signal()
        if self.position:
            if self.position.size > 0 and signal == 'sell':
                self._cancel_exit_orders()
                self.close()
                self.log('CLOSE LONG BY OPPOSITE SIGNAL')
                return
            if self.position.size < 0 and signal == 'buy':
                self._cancel_exit_orders()
                self.close()
                self.log('CLOSE SHORT BY OPPOSITE SIGNAL')
                return
            return
        size = max(0.01, float(self.p.fixed_lot))
        if signal == 'buy':
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log('OPEN BUY')
            return
        if signal == 'sell':
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log('OPEN SELL')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order == self.entry_order:
            if order.status == order.Completed:
                self.entry_order = None
                self._place_exit_orders()
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.entry_order = None
                return
        if order == self.stop_order:
            if order.status == order.Completed:
                self.stop_order = None
                self.limit_order = None
                self.stop_price = None
                self.limit_price = None
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.stop_order = None
                return
        if order == self.limit_order:
            if order.status == order.Completed:
                self.limit_order = None
                self.stop_order = None
                self.stop_price = None
                self.limit_price = None
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._cancel_exit_orders()
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
