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


class IndexedMovingAverage(bt.Indicator):
    lines = ('ima',)
    params = dict(period=5)

    def __init__(self):
        self.ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.period)
        self.addminperiod(self.p.period + 1)

    def next(self):
        ma = float(self.ma[0])
        close = float(self.data.close[0])
        self.lines.ima[0] = 0.0 if abs(ma) < 1e-12 else (close / ma) - 1.0


class IndexedMovingAverageStrategy(bt.Strategy):
    params = dict(
        ma_period=5,
        take=50,
        drop=1000,
        signal_level=0.5,
        risk=0.01,
        max_lots=1.0,
        volume_min=0.1,
        volume_step=0.1,
        volume_max=100.0,
        margin_per_lot=250.0,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ima = IndexedMovingAverage(self.data, period=self.p.ma_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self.order = None
        self.entry_price = None
        self.stop_price = None
        self.last_signal_k = 0.0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_volume_down(self, value):
        if value <= 0:
            return 0.0
        steps = int(value / self.p.volume_step)
        return round(steps * self.p.volume_step, 8)

    def _calc_lot(self):
        cash = float(self.broker.getcash())
        lot = cash * self.p.risk / max(self.p.drop, 1)
        lot = self._round_volume_down(lot)
        if self.p.max_lots > 0:
            lot = min(lot, self.p.max_lots)
        lot = min(lot, self.p.volume_max)
        while lot >= self.p.volume_min and cash < lot * self.p.margin_per_lot:
            lot = self._round_volume_down(lot - self.p.volume_step)
        if lot < self.p.volume_min:
            return 0.0
        return round(lot, 8)

    def _loss_points(self):
        if not self.position or self.entry_price is None:
            return 0.0
        close = float(self.data.close[0])
        if self.position.size > 0:
            return max(0.0, (self.entry_price - close) / self.p.point)
        return max(0.0, (close - self.entry_price) / self.p.point)

    def _profit_points(self):
        if not self.position or self.entry_price is None:
            return 0.0
        close = float(self.data.close[0])
        if self.position.size > 0:
            return max(0.0, (close - self.entry_price) / self.p.point)
        return max(0.0, (self.entry_price - close) / self.p.point)

    def _update_trailing_stop(self):
        profit_points = self._profit_points()
        if profit_points <= self.p.take:
            return
        close = float(self.data.close[0])
        if self.position.size > 0:
            new_stop = round(close - self.p.take * self.p.point, self.p.price_digits)
            if self.stop_price is None or new_stop > self.stop_price:
                self.stop_price = new_stop
        elif self.position.size < 0:
            new_stop = round(close + self.p.take * self.p.point, self.p.price_digits)
            if self.stop_price is None or new_stop < self.stop_price:
                self.stop_price = new_stop

    def _check_stop_hit(self):
        if self.stop_price is None or not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0 and low <= self.stop_price:
            self.log(f'close long trailing_stop={self.stop_price:.2f}')
            self.order = self.close()
            return True
        if self.position.size < 0 and high >= self.stop_price:
            self.log(f'close short trailing_stop={self.stop_price:.2f}')
            self.order = self.close()
            return True
        return False

    def next(self):
        self.bar_num += 1
        warmup = self.p.ma_period + 3
        if len(self.data) < warmup:
            return
        if self.order:
            return

        if self.position:
            if self._check_stop_hit():
                return
            loss_points = self._loss_points()
            if loss_points >= self.p.drop:
                self.log(f'close loss drop_points={loss_points:.2f}')
                self.order = self.close()
                return
            self._update_trailing_stop()
            return

        ima0 = float(self.ima.ima[0])
        ima1 = float(self.ima.ima[-1])
        if abs(ima1) < 1e-12:
            self.last_signal_k = 0.0
            return
        k1 = (ima0 - ima1) / abs(ima1)
        self.last_signal_k = k1
        lot = self._calc_lot()
        if lot < self.p.volume_min:
            return
        if k1 >= self.p.signal_level:
            self.log(f'buy signal k={k1:.4f} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return
        if k1 <= -self.p.signal_level:
            self.log(f'sell signal k={k1:.4f} lot={lot:.2f}')
            self.order = self.sell(size=lot)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.position:
                self.entry_price = float(order.executed.price)
                self.stop_price = None
                side = 'long' if self.position.size > 0 else 'short'
                self.log(f'{side} filled price={self.entry_price:.2f} size={abs(self.position.size):.2f}')
            else:
                self.entry_price = None
                self.stop_price = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if not self.position:
                self.entry_price = None
                self.stop_price = None
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
