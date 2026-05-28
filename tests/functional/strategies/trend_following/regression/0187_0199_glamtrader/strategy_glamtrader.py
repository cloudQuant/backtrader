from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
LOCAL_BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(LOCAL_BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(LOCAL_BACKTRADER_REPO))

import backtrader as bt


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

    weighted_price = (df['high'] + df['low'] + 2.0 * df['close']) / 4.0
    weights = np.arange(1, 15)
    df['ma'] = weighted_price.rolling(14).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

    median_price = (df['high'] + df['low']) / 2.0
    df['ao'] = median_price.rolling(5).mean() - median_price.rolling(34).mean()

    gamma = 0.7
    l0 = l1 = l2 = l3 = None
    laguerre_values = []
    for price in df['close'].tolist():
        if l0 is None:
            l0 = l1 = l2 = l3 = float(price)
        l0_prev, l1_prev, l2_prev, l3_prev = l0, l1, l2, l3
        l0 = (1.0 - gamma) * price + gamma * l0_prev
        l1 = -gamma * l0 + l0_prev + gamma * l1_prev
        l2 = -gamma * l1 + l1_prev + gamma * l2_prev
        l3 = -gamma * l2 + l2_prev + gamma * l3_prev
        cu = 0.0
        cd = 0.0
        if l0 >= l1:
            cu += l0 - l1
        else:
            cd += l1 - l0
        if l1 >= l2:
            cu += l1 - l2
        else:
            cd += l2 - l1
        if l2 >= l3:
            cu += l2 - l3
        else:
            cd += l3 - l2
        laguerre_values.append(cu / (cu + cd) if (cu + cd) else 0.0)
    df['laguerre'] = laguerre_values

    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('ma', 'ao', 'laguerre',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('ma', 6), ('ao', 7), ('laguerre', 8),
    )


class WeightedPrice(bt.Indicator):
    lines = ('weighted',)

    def next(self):
        self.lines.weighted[0] = (
            float(self.data.high[0])
            + float(self.data.low[0])
            + 2.0 * float(self.data.close[0])
        ) / 4.0


class AwesomeOscillator(bt.Indicator):
    lines = ('ao',)
    params = dict(fast=5, slow=34)

    def __init__(self):
        median_price = (self.data.high + self.data.low) / 2.0
        self._fast = bt.indicators.SimpleMovingAverage(median_price, period=self.p.fast)
        self._slow = bt.indicators.SimpleMovingAverage(median_price, period=self.p.slow)

    def next(self):
        self.lines.ao[0] = float(self._fast[0]) - float(self._slow[0])


class LaguerreIndicator(bt.Indicator):
    lines = ('laguerre',)
    params = dict(gamma=0.7)

    def __init__(self):
        self.addminperiod(2)
        self._l0 = None
        self._l1 = None
        self._l2 = None
        self._l3 = None

    def next(self):
        price = float(self.data.close[0])
        gamma = self.p.gamma
        if self._l0 is None:
            self._l0 = price
            self._l1 = price
            self._l2 = price
            self._l3 = price

        l0_prev = self._l0
        l1_prev = self._l1
        l2_prev = self._l2
        l3_prev = self._l3

        l0 = (1.0 - gamma) * price + gamma * l0_prev
        l1 = -gamma * l0 + l0_prev + gamma * l1_prev
        l2 = -gamma * l1 + l1_prev + gamma * l2_prev
        l3 = -gamma * l2 + l2_prev + gamma * l3_prev

        cu = 0.0
        cd = 0.0
        if l0 >= l1:
            cu += l0 - l1
        else:
            cd += l1 - l0
        if l1 >= l2:
            cu += l1 - l2
        else:
            cd += l2 - l1
        if l2 >= l3:
            cu += l2 - l3
        else:
            cd += l3 - l2

        self.lines.laguerre[0] = cu / (cu + cd) if (cu + cd) else 0.0
        self._l0 = l0
        self._l1 = l1
        self._l2 = l2
        self._l3 = l3


class GlamTraderStrategy(bt.Strategy):
    params = dict(
        lot=1.0,
        stop_loss_buy=50,
        take_profit_buy=50,
        stop_loss_sell=50,
        take_profit_sell=50,
        trailing_stop=5,
        trailing_step=15,
        ma_period=14,
        ma_shift=1,
        laguerre_gamma=0.7,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ma = self.data.ma
        self.ao = self.data.ao
        self.laguerre = self.data.laguerre
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._pending_side = None
        self._current_stop = None
        self._current_take_profit = None
        self._entry_price = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _clear_risk_levels(self):
        self._current_stop = None
        self._current_take_profit = None
        self._entry_price = None

    def _update_initial_risk_levels(self, side, entry_price):
        if side == 'buy':
            self._current_stop = entry_price - self.p.stop_loss_buy * self.p.point if self.p.stop_loss_buy else None
            self._current_take_profit = entry_price + self.p.take_profit_buy * self.p.point if self.p.take_profit_buy else None
        else:
            self._current_stop = entry_price + self.p.stop_loss_sell * self.p.point if self.p.stop_loss_sell else None
            self._current_take_profit = entry_price - self.p.take_profit_sell * self.p.point if self.p.take_profit_sell else None
        self._entry_price = entry_price

    def _maybe_hit_exit_levels(self):
        if not self.position:
            return False
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position.size > 0:
            if self._current_stop is not None and low <= self._current_stop:
                self.log(f'close long stop={self._current_stop:.2f}')
                self.close()
                return True
            if self._current_take_profit is not None and high >= self._current_take_profit:
                self.log(f'close long take_profit={self._current_take_profit:.2f}')
                self.close()
                return True
        else:
            if self._current_stop is not None and high >= self._current_stop:
                self.log(f'close short stop={self._current_stop:.2f}')
                self.close()
                return True
            if self._current_take_profit is not None and low <= self._current_take_profit:
                self.log(f'close short take_profit={self._current_take_profit:.2f}')
                self.close()
                return True
        return False

    def _apply_trailing(self):
        if not self.position or self.p.trailing_stop == 0:
            return
        close_price = float(self.data.close[0])
        if self.position.size > 0:
            if close_price - self._entry_price > (self.p.trailing_stop + self.p.trailing_step) * self.p.point:
                new_stop = close_price - self.p.trailing_stop * self.p.point
                threshold = close_price - (self.p.trailing_stop + self.p.trailing_step) * self.p.point
                if self._current_stop is None or self._current_stop < threshold:
                    self._current_stop = new_stop
                    self.log(f'update long trailing_stop={new_stop:.2f}')
        else:
            if self._entry_price - close_price > (self.p.trailing_stop + self.p.trailing_step) * self.p.point:
                new_stop = close_price + self.p.trailing_stop * self.p.point
                threshold = close_price + (self.p.trailing_stop + self.p.trailing_step) * self.p.point
                if self._current_stop is None or self._current_stop > threshold:
                    self._current_stop = new_stop
                    self.log(f'update short trailing_stop={new_stop:.2f}')

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.ma_period + self.p.ma_shift + 2, 40)
        if len(self.data) < warmup:
            return

        if self._maybe_hit_exit_levels():
            return

        if self.position:
            self._apply_trailing()
            return

        ma_value = float(self.ma[0])
        close_value = float(self.data.close[0])
        laguerre_value = float(self.laguerre[0])
        ao_now = float(self.ao[0])
        ao_prev = float(self.ao[-1])

        buy_signal = ma_value > close_value and laguerre_value > 0.15 and ao_now > ao_prev
        sell_signal = ma_value < close_value and laguerre_value < 0.75 and ao_now < ao_prev

        if buy_signal:
            self._pending_side = 'buy'
            self.log(f'buy ma={ma_value:.2f} close={close_value:.2f} laguerre={laguerre_value:.4f} ao={ao_now:.4f}')
            self.buy(size=self.p.lot)
            return
        if sell_signal:
            self._pending_side = 'sell'
            self.log(f'sell ma={ma_value:.2f} close={close_value:.2f} laguerre={laguerre_value:.4f} ao={ao_now:.4f}')
            self.sell(size=self.p.lot)
            return

    def notify_order(self, order):
        if order.status != order.Completed:
            return
        if order.isbuy() and self.position.size > 0:
            self._update_initial_risk_levels('buy', order.executed.price)
        elif order.issell() and self.position.size < 0:
            self._update_initial_risk_levels('sell', order.executed.price)

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
        self._pending_side = None
        self._clear_risk_levels()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
