from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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


class EmaWmaV2Strategy(bt.Strategy):
    params = dict(
        ema_period=28,
        wma_period=8,
        stop_loss_pips=50,
        take_profit_pips=50,
        trailing_stop_pips=50,
        trailing_step_pips=10,
        risk_pct=10.0,
        margin_per_lot=250.0,
        min_lot=0.1,
        max_lot=100.0,
        lot_decimals=1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ema = bt.ind.ExponentialMovingAverage(self.data.open, period=self.p.ema_period)
        self.wma = bt.ind.WeightedMovingAverage(self.data.open, period=self.p.wma_period)
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
        self._last_position_size = 0.0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        digits_adjust = 10 if self.p.price_digits in (3, 5) else 1
        return self.p.point * digits_adjust

    def _calc_lot(self):
        cash = float(self.broker.getcash())
        raw_lot = cash * float(self.p.risk_pct) / 100.0 / float(self.p.margin_per_lot)
        raw_lot = min(max(raw_lot, float(self.p.min_lot)), float(self.p.max_lot))
        factor = 10 ** int(self.p.lot_decimals)
        return math.floor(raw_lot * factor + 1e-9) / factor

    def _clear_position_state(self):
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
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

    def _update_trailing(self):
        if not self.position or self._entry_price is None or self.p.trailing_stop_pips <= 0:
            return
        pip_size = self._pip_size()
        trailing_distance = self.p.trailing_stop_pips * pip_size
        trailing_step = self.p.trailing_step_pips * pip_size
        close = float(self.data.close[0])
        if self.position.size > 0:
            if close - self._entry_price > trailing_distance + trailing_step:
                candidate = close - trailing_distance
                if self._stop_price is None or candidate > self._stop_price:
                    self._stop_price = candidate
        else:
            if self._entry_price - close > trailing_distance + trailing_step:
                candidate = close + trailing_distance
                if self._stop_price is None or candidate < self._stop_price:
                    self._stop_price = candidate

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

    def _buy_signal(self):
        return float(self.ema[0]) < float(self.wma[0]) and float(self.ema[-1]) > float(self.wma[-1])

    def _sell_signal(self):
        return float(self.ema[0]) > float(self.wma[0]) and float(self.ema[-1]) < float(self.wma[-1])

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(self.p.ema_period, self.p.wma_period) + 2:
            return
        if self.order:
            return

        if self.position:
            self._set_initial_protection()
            self._update_trailing()
            if self._maybe_hit_exit():
                return

        size = self._calc_lot()
        if size <= 0:
            return

        if self._buy_signal():
            if self.position.size > 0:
                return
            self.log(f'buy cross lot={size:.1f}')
            self.order = self.order_target_size(target=size)
            return

        if self._sell_signal():
            if self.position.size < 0:
                return
            self.log(f'sell cross lot={size:.1f}')
            self.order = self.order_target_size(target=-size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if self.position.size > 0 and order.executed.size > 0:
                self.buy_count += 1
                self._set_initial_protection()
            elif self.position.size < 0 and order.executed.size < 0:
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
