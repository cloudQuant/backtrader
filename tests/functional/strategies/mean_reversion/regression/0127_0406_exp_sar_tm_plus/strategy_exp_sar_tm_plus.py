from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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


class ExpSarTmPlusStrategy(bt.Strategy):
    params = dict(
        mm=0.1,
        mm_mode='LOT',
        stop_loss_points=1000,
        take_profit_points=2000,
        deviation_points=10,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        time_trade=True,
        hold_minutes=240,
        sar_step=0.02,
        sar_maximum=0.2,
        signal_bar=1,
        lot=0.10,
        point=0.01,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.data1 = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.sar = bt.indicators.ParabolicSAR(self.data1, af=self.p.sar_step, afmax=self.p.sar_maximum)
        self.order = None
        self.pending_action = None
        self.entry_dt = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        if self.order is not None:
            return
        if len(self.data1) <= int(self.p.signal_bar) + 1:
            return

        self._check_exit_levels()
        if self.order is not None:
            return

        if self.p.time_trade and self.position and self.entry_dt is not None:
            current_dt = bt.num2date(self.data0.datetime[0])
            if (current_dt - self.entry_dt).total_seconds() >= int(self.p.hold_minutes) * 60:
                self.pending_action = 'close'
                self.order = self.close()
                self.log('CLOSE POSITION by holding time')
                return

        signal_dt = bt.num2date(self.data1.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        newer_shift = int(self.p.signal_bar)
        older_shift = newer_shift + 1
        older_close = self._finite(self.data1.close[-older_shift])
        older_sar = self._finite(self.sar[-older_shift])
        newer_close = self._finite(self.data1.close[-newer_shift])
        newer_sar = self._finite(self.sar[-newer_shift])
        if None in (older_close, older_sar, newer_close, newer_sar):
            return

        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False

        if newer_close > newer_sar and older_close < older_sar:
            if self.p.buy_pos_open:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True

        if newer_close < newer_sar and older_close > older_sar:
            if self.p.sell_pos_open:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True

        if self.position.size > 0 and buy_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE LONG by SAR reversal')
            return
        if self.position.size < 0 and sell_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE SHORT by SAR reversal')
            return

        if self.position:
            return

        if buy_open:
            self.pending_action = 'open_long'
            self.order = self.buy(size=float(self.p.lot))
            self._prepare_entry_levels('long', float(self.data0.close[0]))
            self.log(f'OPEN LONG newer_close={newer_close:.5f} newer_sar={newer_sar:.5f}')
            return
        if sell_open:
            self.pending_action = 'open_short'
            self.order = self.sell(size=float(self.p.lot))
            self._prepare_entry_levels('short', float(self.data0.close[0]))
            self.log(f'OPEN SHORT newer_close={newer_close:.5f} newer_sar={newer_sar:.5f}')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.pending_action == 'open_long' and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self.entry_price = float(order.executed.price)
                self.entry_dt = bt.num2date(self.data0.datetime[0])
                self._prepare_entry_levels('long', self.entry_price)
            elif self.pending_action == 'open_short' and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self.entry_price = float(order.executed.price)
                self.entry_dt = bt.num2date(self.data0.datetime[0])
                self._prepare_entry_levels('short', self.entry_price)
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
        high_0 = float(self.data0.high[0])
        low_0 = float(self.data0.low[0])
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
        if self.position.size < 0:
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

    def _prepare_entry_levels(self, side, reference_price):
        self.entry_price = float(reference_price)
        if side == 'long':
            self.stop_price = self.entry_price - self._distance(self.p.stop_loss_points) if self.p.stop_loss_points else None
            self.take_profit_price = self.entry_price + self._distance(self.p.take_profit_points) if self.p.take_profit_points else None
        else:
            self.stop_price = self.entry_price + self._distance(self.p.stop_loss_points) if self.p.stop_loss_points else None
            self.take_profit_price = self.entry_price - self._distance(self.p.take_profit_points) if self.p.take_profit_points else None

    def _clear_trade_levels(self):
        self.entry_dt = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    @staticmethod
    def _finite(value):
        value = float(value)
        if not math.isfinite(value):
            return None
        return value

    def _distance(self, points):
        return float(points) * float(self.p.point)
