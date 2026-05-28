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


class Mt5PandasFeed(btfeeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class MeanReversionStrategy(bt.Strategy):
    params = dict(
        lookback=200,
        risk_per_trade=1.0,
        min_lot=0.01,
        lot_step=0.01,
        max_lot=100.0,
        multiplier=100.0,
        verbose=False,
    )

    def __init__(self):
        self.lowest = bt.indicators.Lowest(self.data.low, period=self.p.lookback)
        self.highest = bt.indicators.Highest(self.data.high, period=self.p.lookback)
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
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

    def _current_mean(self):
        return (float(self.highest[0]) + float(self.lowest[0])) / 2.0

    def _normalize_lot(self, lot):
        step = float(self.p.lot_step)
        if step <= 0:
            step = 0.01
        lot = math.floor(lot / step) * step
        lot = min(max(lot, float(self.p.min_lot)), float(self.p.max_lot))
        return round(lot, 8)

    def _calculate_lot(self, entry_price, stop_price):
        risk_cash = self.broker.getvalue() * (float(self.p.risk_per_trade) / 100.0)
        stop_distance = abs(float(entry_price) - float(stop_price))
        if stop_distance <= 0:
            return float(self.p.min_lot)
        risk_per_lot = stop_distance * float(self.p.multiplier)
        if risk_per_lot <= 0:
            return float(self.p.min_lot)
        raw_lot = risk_cash / risk_per_lot
        return self._normalize_lot(raw_lot)

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _place_exit_orders(self):
        if not self.position:
            return
        self._cancel_exit_orders()
        size = abs(self.position.size)
        if self.position.size > 0:
            tp = self.position.price + (self.position.price - self.position.price)  # placeholder overwritten by trade metadata absence
        if hasattr(self, 'pending_tp') and hasattr(self, 'pending_sl'):
            if self.position.size > 0:
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.pending_sl)
                self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=self.pending_tp, oco=self.stop_order)
            else:
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.pending_sl)
                self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=self.pending_tp, oco=self.stop_order)

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.lookback:
            return
        if self.entry_order is not None or self.position:
            return

        mean_value = self._current_mean()
        current_low = float(self.data.low[0])
        current_high = float(self.data.high[0])
        lowest_value = float(self.lowest[0])
        highest_value = float(self.highest[0])

        if current_low <= lowest_value:
            entry = float(self.data.close[0])
            tp = mean_value
            sl = 2.0 * entry - tp
            size = self._calculate_lot(entry, sl)
            self.pending_tp = tp
            self.pending_sl = sl
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN BUY size={size} tp={tp:.2f} sl={sl:.2f}')
            return

        if current_high >= highest_value:
            entry = float(self.data.close[0])
            tp = mean_value
            sl = 2.0 * entry - tp
            size = self._calculate_lot(entry, sl)
            self.pending_tp = tp
            self.pending_sl = sl
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SELL size={size} tp={tp:.2f} sl={sl:.2f}')

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
                return
            if order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.stop_order = None
                return
        if order == self.limit_order:
            if order.status == order.Completed:
                self.limit_order = None
                self.stop_order = None
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
