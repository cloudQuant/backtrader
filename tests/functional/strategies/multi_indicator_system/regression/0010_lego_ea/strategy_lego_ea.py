from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

import pandas as pd

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
LOCAL_BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(LOCAL_BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(LOCAL_BACKTRADER_REPO))

import backtrader as bt


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0, ma_fast_period=14, ma_slow_period=67, ma_shift=1):
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
    df['ma_fast'] = df['close'].rolling(ma_fast_period).mean().shift(ma_shift)
    df['ma_slow'] = df['close'].rolling(ma_slow_period).mean().shift(ma_shift)
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('ma_fast', 'ma_slow',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('ma_fast', 6), ('ma_slow', 7),
    )


class LegoEAStrategy(bt.Strategy):
    params = dict(
        lot=1.0,
        stop_loss_points=200,
        take_profit_points=200,
        lot_multiply=2.0,
        ma_fast_period=14,
        ma_slow_period=67,
        ma_shift=1,
        point=0.01,
    )

    def __init__(self):
        self.ma_fast = self.data.ma_fast
        self.ma_slow = self.data.ma_slow
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.order = None
        self._position_was_open = False
        self._current_stop = None
        self._current_take_profit = None
        self._current_entry_side = None
        self._active_lot = self.p.lot
        self._last_deal_loss = False
        self._last_deal_lot = self.p.lot

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _next_lot(self):
        if self._last_deal_loss:
            return self._last_deal_lot * self.p.lot_multiply
        return self.p.lot

    def _set_risk_levels(self, side, entry_price):
        if side == 'buy':
            self._current_stop = entry_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
            self._current_take_profit = entry_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points else None
        else:
            self._current_stop = entry_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points else None
            self._current_take_profit = entry_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points else None

    def _clear_risk_levels(self):
        self._current_stop = None
        self._current_take_profit = None
        self._current_entry_side = None

    def _maybe_hit_exit_levels(self):
        if not self.position:
            return False
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position.size > 0:
            if self._current_stop is not None and low <= self._current_stop:
                self.log(f'close long stop={self._current_stop:.2f}')
                self.order = self.close()
                return True
            if self._current_take_profit is not None and high >= self._current_take_profit:
                self.log(f'close long take_profit={self._current_take_profit:.2f}')
                self.order = self.close()
                return True
        else:
            if self._current_stop is not None and high >= self._current_stop:
                self.log(f'close short stop={self._current_stop:.2f}')
                self.order = self.close()
                return True
            if self._current_take_profit is not None and low <= self._current_take_profit:
                self.log(f'close short take_profit={self._current_take_profit:.2f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order:
            return
        if len(self.data) < self.p.ma_slow_period + self.p.ma_shift + 2:
            return
        ma_fast = float(self.ma_fast[0])
        ma_slow = float(self.ma_slow[0])
        if pd.isna(ma_fast) or pd.isna(ma_slow):
            return

        open_buy = ma_fast > ma_slow
        open_sell = ma_fast < ma_slow
        close_buy = ma_fast < ma_slow
        close_sell = ma_fast > ma_slow

        if self.position:
            if self._maybe_hit_exit_levels():
                return
            if self.position.size > 0 and close_buy:
                self.log(f'close long ma_fast={ma_fast:.2f} ma_slow={ma_slow:.2f}')
                self.order = self.close()
                return
            if self.position.size < 0 and close_sell:
                self.log(f'close short ma_fast={ma_fast:.2f} ma_slow={ma_slow:.2f}')
                self.order = self.close()
                return
            return

        if open_buy and not close_buy:
            size = self._next_lot()
            self._active_lot = size
            self._current_entry_side = 'buy'
            self.log(f'buy size={size:.2f} ma_fast={ma_fast:.2f} ma_slow={ma_slow:.2f}')
            self.order = self.buy(size=size)
            return
        if open_sell and not close_sell:
            size = self._next_lot()
            self._active_lot = size
            self._current_entry_side = 'sell'
            self.log(f'sell size={size:.2f} ma_fast={ma_fast:.2f} ma_slow={ma_slow:.2f}')
            self.order = self.sell(size=size)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and self.position.size > 0:
                self._set_risk_levels('buy', order.executed.price)
            elif order.issell() and self.position.size < 0:
                self._set_risk_levels('sell', order.executed.price)
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
        if trade.pnlcomm > 0:
            self.win_count += 1
            self._last_deal_loss = False
        else:
            self.loss_count += 1
            self._last_deal_loss = True
        self._last_deal_lot = self._active_lot
        self._position_was_open = False
        self._clear_risk_levels()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
