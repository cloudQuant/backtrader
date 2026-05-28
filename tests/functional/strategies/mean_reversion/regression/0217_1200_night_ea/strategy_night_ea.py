from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_SRC = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_SRC) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_SRC))

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5StochasticCloseClose(bt.Indicator):
    lines = ('main', 'signal')
    params = dict(k_period=5, d_period=3, slowing=3)

    def __init__(self):
        self.addminperiod(self.p.k_period + max(self.p.d_period, self.p.slowing) + 2)
        self._slow_prev = None
        self._signal_prev = None
        self._alpha_slow = 2.0 / (self.p.slowing + 1.0)
        self._alpha_signal = 2.0 / (self.p.d_period + 1.0)

    def next(self):
        closes = [float(self.data.close[-i]) for i in range(self.p.k_period)]
        highest_close = max(closes)
        lowest_close = min(closes)
        close0 = float(self.data.close[0])
        if highest_close == lowest_close:
            raw_k = 0.0
        else:
            raw_k = 100.0 * (close0 - lowest_close) / (highest_close - lowest_close)

        if self._slow_prev is None:
            slow_val = raw_k
        else:
            slow_val = self._slow_prev + self._alpha_slow * (raw_k - self._slow_prev)

        if self._signal_prev is None:
            signal_val = slow_val
        else:
            signal_val = self._signal_prev + self._alpha_signal * (slow_val - self._signal_prev)

        self.lines.main[0] = slow_val
        self.lines.signal[0] = signal_val
        self._slow_prev = slow_val
        self._signal_prev = signal_val


class NightEaStrategy(bt.Strategy):
    params = dict(
        stoch_k_period=5,
        stoch_d_period=3,
        stoch_slowing=3,
        stoch_oversold=30,
        stoch_overbought=70,
        stop_loss_points=40,
        take_profit_points=20,
        trade_start_hour=21,
        trade_end_hour=6,
        lot_divisor=10000.0,
        min_lot=0.1,
        max_lot=5.0,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.stoch = Mt5StochasticCloseClose(
            self.data,
            k_period=self.p.stoch_k_period,
            d_period=self.p.stoch_d_period,
            slowing=self.p.stoch_slowing,
        )
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_entry_size = 0.0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _in_trade_window(self):
        dt = bt.num2date(self.data.datetime[0])
        return dt.hour >= self.p.trade_start_hour or dt.hour < self.p.trade_end_hour

    def _calc_volume(self):
        lots = self.broker.getcash() / self.p.lot_divisor
        lots = min(self.p.max_lot, max(self.p.min_lot, lots))
        if lots < 0.1:
            return round(lots, 2)
        if lots < 1:
            return round(lots, 1)
        return round(lots, 0)

    def _clear_exit_levels(self):
        self.stop_price = None
        self.take_profit_price = None
        self.entry_side = None
        self.last_entry_size = 0.0

    def next(self):
        self.bar_num += 1
        warmup = self.p.stoch_k_period + max(self.p.stoch_d_period, self.p.stoch_slowing) + 5
        if len(self.data) < warmup:
            return

        if self.order:
            return

        high = float(self.data.high[0])
        low = float(self.data.low[0])

        if self.position:
            if self.position.size > 0:
                if self.stop_price is not None and low <= self.stop_price:
                    self.log(f'close long stop={self.stop_price:.2f}')
                    self.order = self.close()
                    return
                if self.take_profit_price is not None and high >= self.take_profit_price:
                    self.log(f'close long tp={self.take_profit_price:.2f}')
                    self.order = self.close()
                    return
            elif self.position.size < 0:
                if self.stop_price is not None and high >= self.stop_price:
                    self.log(f'close short stop={self.stop_price:.2f}')
                    self.order = self.close()
                    return
                if self.take_profit_price is not None and low <= self.take_profit_price:
                    self.log(f'close short tp={self.take_profit_price:.2f}')
                    self.order = self.close()
                    return
            return

        if not self._in_trade_window():
            return

        stoch_prev = float(self.stoch.main[-1])
        size = self._calc_volume()
        if stoch_prev < self.p.stoch_oversold:
            self.entry_side = 'long'
            self.last_entry_size = size
            self.log(f'buy signal stoch_prev={stoch_prev:.2f} size={size:.2f}')
            self.order = self.buy(size=size)
            return
        if stoch_prev > self.p.stoch_overbought:
            self.entry_side = 'short'
            self.last_entry_size = size
            self.log(f'sell signal stoch_prev={stoch_prev:.2f} size={size:.2f}')
            self.order = self.sell(size=size)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy() and self.entry_side == 'long' and self.position.size > 0:
                price = float(order.executed.price)
                self.stop_price = round(price - self.p.stop_loss_points * self.p.point, self.p.price_digits)
                self.take_profit_price = round(price + self.p.take_profit_points * self.p.point, self.p.price_digits)
                self.log(f'long filled price={price:.2f} sl={self.stop_price:.2f} tp={self.take_profit_price:.2f}')
            elif order.issell() and self.entry_side == 'short' and self.position.size < 0:
                price = float(order.executed.price)
                self.stop_price = round(price + self.p.stop_loss_points * self.p.point, self.p.price_digits)
                self.take_profit_price = round(price - self.p.take_profit_points * self.p.point, self.p.price_digits)
                self.log(f'short filled price={price:.2f} sl={self.stop_price:.2f} tp={self.take_profit_price:.2f}')
            elif not self.position:
                self._clear_exit_levels()
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if not self.position:
                self._clear_exit_levels()
            self.log(f'order {order.getstatusname()}')

        self.order = None

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
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
