from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
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



def resample_ohlcv(df, rule):
    agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
        'spread': 'last',
    }
    out = df.resample(rule, label='right', closed='right').agg(agg).dropna()
    return out


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class PuriaMethodStrategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        stop_loss_pips=150,
        take_profit_pips=0,
        trailing_stop_pips=45,
        trailing_step_pips=5,
        min_profit_step_pips=100,
        min_profit_percent=0.5,
        macd_number_bars=8,
        point_size=0.01,
        verbose=False,
        min_lot=0.01,
        lot_step=0.01,
    )

    def __init__(self):
        price_high = self.data.high
        price_open = self.data.open
        self.ma0 = bt.indicators.SmoothedMovingAverage(price_high, period=69)
        self.ma1 = bt.indicators.SmoothedMovingAverage(price_high, period=74)
        self.ma2 = bt.indicators.ExponentialMovingAverage(price_open, period=19)
        self.macd = bt.indicators.MACD(price_open, period_me1=17, period_me2=38, period_signal=1)
        self.last_bar_dt = None
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.stop_price = None
        self.limit_price = None
        self.partial_target_size = None
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

    def _round_lot(self, size):
        step = float(self.p.lot_step)
        min_lot = float(self.p.min_lot)
        if size < min_lot:
            return 0.0
        rounded = math.floor(size / step + 1e-9) * step
        return round(rounded, 8) if rounded >= min_lot else 0.0

    def _update_trailing_stop(self):
        if not self.position or self.p.trailing_stop_pips <= 0:
            return
        trailing_distance = float(self.p.trailing_stop_pips) * float(self.p.point_size)
        trailing_step = float(self.p.trailing_step_pips) * float(self.p.point_size)
        close_price = float(self.data.close[0])
        if self.position.size > 0:
            if close_price - self.position.price <= trailing_distance + trailing_step:
                return
            candidate = close_price - trailing_distance
            if self.stop_price is None or candidate > self.stop_price + trailing_step:
                self.stop_price = candidate
                size = abs(self.position.size)
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.limit_order)
        else:
            if self.position.price - close_price <= trailing_distance + trailing_step:
                return
            candidate = close_price + trailing_distance
            if self.stop_price is None or candidate < self.stop_price - trailing_step:
                self.stop_price = candidate
                size = abs(self.position.size)
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price, oco=self.limit_order)

    def _macd_trend_up(self):
        count = max(3, int(self.p.macd_number_bars) + 1)
        for i in range(count - 1):
            if float(self.macd.macd[-(i + 2)]) > float(self.macd.macd[-(i + 1)]):
                return False
        return True

    def _macd_trend_down(self):
        count = max(3, int(self.p.macd_number_bars) + 1)
        for i in range(count - 1):
            if float(self.macd.macd[-(i + 2)]) < float(self.macd.macd[-(i + 1)]):
                return False
        return True

    def _check_signal(self):
        count = max(3, int(self.p.macd_number_bars) + 1)
        if min(len(self.ma0), len(self.ma1), len(self.ma2), len(self.macd.macd)) < count + 2:
            return None
        threshold = 0.5 * float(self.p.point_size)
        ma0_1 = float(self.ma0[-1])
        ma1_1 = float(self.ma1[-1])
        ma2_1 = float(self.ma2[-1])
        macd_1 = float(self.macd.macd[-1])
        if (ma1_1 - ma0_1) > threshold and (ma2_1 - ma0_1) > threshold and macd_1 > 0.0 and self._macd_trend_up():
            return 'buy'
        if (ma0_1 - ma1_1) > threshold and (ma0_1 - ma2_1) > threshold and macd_1 < 0.0 and self._macd_trend_down():
            return 'sell'
        return None

    def _maybe_partial_close(self):
        if not self.position:
            return False
        threshold = float(self.p.min_profit_step_pips) * float(self.p.point_size)
        if threshold <= 0:
            return False
        current_price = float(self.data.close[0])
        open_price = float(self.position.price)
        if self.position.size > 0 and current_price < open_price + threshold:
            return False
        if self.position.size < 0 and current_price > open_price - threshold:
            return False
        target = self._round_lot(abs(self.position.size) * float(self.p.min_profit_percent))
        if target <= 0.0:
            return False
        if target >= abs(self.position.size):
            target = self._round_lot(abs(self.position.size) - float(self.p.min_lot))
        if target <= 0.0:
            return False
        self._cancel_exit_orders()
        self.partial_target_size = target
        if self.position.size > 0:
            self.sell(size=target)
        else:
            self.buy(size=target)
        self.log(f'PARTIAL CLOSE size={target:.2f}')
        return True

    def next(self):
        self.bar_num += 1
        if not self._new_bar():
            return
        if self.entry_order is not None:
            return
        self._update_trailing_stop()
        signal = self._check_signal()
        if self.position:
            self._maybe_partial_close()
            return
        size = max(float(self.p.min_lot), float(self.p.fixed_lot))
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
        if self.position.size == 0:
            self.trade_count += 1
            if trade.pnlcomm >= 0:
                self.win_count += 1
            else:
                self.loss_count += 1
        self._cancel_exit_orders()
        if self.position:
            self._place_exit_orders()
        self.log(f'TRADE EVENT pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
