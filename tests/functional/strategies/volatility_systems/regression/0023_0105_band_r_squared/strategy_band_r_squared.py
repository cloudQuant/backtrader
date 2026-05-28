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


class DonchianChannel(bt.Indicator):
    lines = ('upper', 'lower')
    params = dict(period=100)

    def __init__(self):
        self.lines.upper = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.lines.lower = bt.indicators.Lowest(self.data.low, period=self.p.period)


class BandRSquaredStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        b_period=100,
        b_deviation=1.0,
        donch_period=100,
        c_period=100,
        atr_period=21,
        stop_atr=4.0,
        take_atr=4.0,
        verbose=False,
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=self.p.b_period, devfactor=self.p.b_deviation)
        self.donch = DonchianChannel(self.data, period=self.p.donch_period)
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_sl = None
        self.pending_tp = None
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
            self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.pending_sl)
            self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=self.pending_tp, oco=self.stop_order)
        else:
            self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.pending_sl)
            self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=self.pending_tp, oco=self.stop_order)

    def _lower_rising(self):
        for i in range(self.p.c_period + 1):
            if float(self.donch.lower[-i]) < float(self.donch.lower[-i - 1]):
                return False
        return True

    def _upper_falling(self):
        for i in range(self.p.c_period + 1):
            if float(self.donch.upper[-i]) > float(self.donch.upper[-i - 1]):
                return False
        return True

    def _buy_signal(self):
        prev_open = float(self.data.open[-1])
        prev_close = float(self.data.close[-1])
        prev_bb_low = float(self.bb.bot[-1])
        return prev_open < prev_bb_low and prev_close > prev_bb_low and self._lower_rising()

    def _sell_signal(self):
        prev_open = float(self.data.open[-1])
        prev_close = float(self.data.close[-1])
        prev_bb_up = float(self.bb.top[-1])
        return prev_open > prev_bb_up and prev_close < prev_bb_up and self._upper_falling()

    def next(self):
        self.bar_num += 1
        min_history = max(self.p.b_period, self.p.donch_period, self.p.atr_period) + self.p.c_period + 5
        if len(self.data) < min_history:
            return

        if self.position:
            prev_close = float(self.data.close[-1])
            prev_donch_up = float(self.donch.upper[-1])
            prev_donch_down = float(self.donch.lower[-1])
            if self.position.size > 0:
                if prev_close > prev_donch_up or prev_close < prev_donch_down:
                    self._cancel_exit_orders()
                    self.close()
                    self.log('CLOSE BUY BY DONCHIAN BREAK')
                    return
            else:
                if prev_close < prev_donch_down or prev_close > prev_donch_up:
                    self._cancel_exit_orders()
                    self.close()
                    self.log('CLOSE SELL BY DONCHIAN BREAK')
                    return

        if self.position or self.entry_order is not None:
            return

        atr_prev = float(self.atr[-1])
        size = float(self.p.lots)
        entry_price = float(self.data.close[0])

        if self._buy_signal():
            self.pending_sl = entry_price - atr_prev * float(self.p.stop_atr)
            self.pending_tp = entry_price + atr_prev * float(self.p.take_atr)
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log('OPEN BUY')
            return

        if self._sell_signal():
            self.pending_sl = entry_price + atr_prev * float(self.p.stop_atr)
            self.pending_tp = entry_price - atr_prev * float(self.p.take_atr)
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
