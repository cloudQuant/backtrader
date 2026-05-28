from __future__ import absolute_import, division, print_function, unicode_literals

import io

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


class SignalFeed(btfeeds.PandasData):
    lines = ('cci',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6), ('cci', 7),
    )


def build_signal_frame(df, indicator_minutes, cci_period):
    rule = f'{int(indicator_minutes)}min'
    signal_df = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
        'spread': 'last',
    })
    signal_df = signal_df.dropna(subset=['open', 'high', 'low', 'close']).copy()
    typical = (signal_df['high'] + signal_df['low'] + signal_df['close']) / 3.0
    sma = typical.rolling(int(cci_period)).mean()
    mad = (typical - sma).abs().rolling(int(cci_period)).mean()
    denom = (0.015 * mad).replace(0, pd.NA)
    signal_df['cci'] = ((typical - sma) / denom).fillna(0.0)
    signal_df['openinterest'] = signal_df['openinterest'].fillna(0)
    signal_df['spread'] = signal_df['spread'].fillna(0)
    return signal_df


class ProbeStrategy(bt.Strategy):
    params = dict(
        lots=1.0,
        point_size=0.01,
        price_digits=2,
        stoploss_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        cci_max_min=120.0,
        indent_pips=30,
        signal_bar=1,
        cci_period=60,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1]
        self.pending_buy = None
        self.pending_sell = None
        self.position_stop = None
        self.stop_cancel_pending = False
        self.stop_replace_price = None
        self.last_signal_dt = None
        self.active_side = None
        self.active_stop_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.exec_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _same_order(self, left, right):
        if left is None or right is None:
            return False
        return getattr(left, 'ref', None) == getattr(right, 'ref', None)

    def _round_price(self, value):
        return round(float(value), int(self.p.price_digits))

    def _cancel_pending(self):
        for order in (self.pending_buy, self.pending_sell):
            if order is not None and order.alive():
                self.cancel(order)
        self.pending_buy = None
        self.pending_sell = None

    def _cancel_stop(self):
        if self.position_stop is not None:
            self.cancel(self.position_stop)
            self.position_stop = None
        self.stop_cancel_pending = False
        self.stop_replace_price = None

    def _place_position_stop(self, stop_price):
        rounded = self._round_price(stop_price)
        if self.position.size > 0:
            self.position_stop = self.sell(size=abs(self.position.size), exectype=bt.Order.Stop, price=rounded)
        elif self.position.size < 0:
            self.position_stop = self.buy(size=abs(self.position.size), exectype=bt.Order.Stop, price=rounded)
        else:
            self.position_stop = None
            return
        self.active_stop_price = rounded
        self.stop_cancel_pending = False
        self.stop_replace_price = None

    def _new_signal_bar(self):
        recent_ago = max(int(self.p.signal_bar), 1) - 1
        current = bt.num2date(self.signal_data.datetime[-recent_ago]) if recent_ago else bt.num2date(self.signal_data.datetime[0])
        if self.last_signal_dt == current:
            return False
        self.last_signal_dt = current
        return True

    def _delete_far_pending(self):
        indent = self.p.indent_pips * self.p.point_size
        if self.pending_buy is not None and self.pending_buy.alive():
            if float(self.pending_buy.created.price) - float(self.exec_data.close[0]) > indent * 1.5:
                self.cancel(self.pending_buy)
                self.pending_buy = None
                self.log('cancel stale buy stop')
        if self.pending_sell is not None and self.pending_sell.alive():
            if float(self.exec_data.close[0]) - float(self.pending_sell.created.price) > indent * 1.5:
                self.cancel(self.pending_sell)
                self.pending_sell = None
                self.log('cancel stale sell stop')

    def _apply_trailing(self):
        if not self.position or self.position_stop is None or self.p.trailing_stop_pips <= 0:
            return
        if self.stop_cancel_pending:
            return
        trail = self.p.trailing_stop_pips * self.p.point_size
        step = self.p.trailing_step_pips * self.p.point_size
        if self.position.size > 0:
            candidate = float(self.exec_data.close[0]) - trail
            if self.active_stop_price is None or candidate - self.active_stop_price >= step:
                self.stop_cancel_pending = True
                self.stop_replace_price = candidate
                self.cancel(self.position_stop)
        else:
            candidate = float(self.exec_data.close[0]) + trail
            if self.active_stop_price is None or self.active_stop_price - candidate >= step:
                self.stop_cancel_pending = True
                self.stop_replace_price = candidate
                self.cancel(self.position_stop)

    def _set_buy_stop(self):
        price = self._round_price(float(self.exec_data.close[0]) + self.p.indent_pips * self.p.point_size)
        self.pending_buy = self.buy(size=self.p.lots, exectype=bt.Order.Stop, price=price)
        self.log(f'set buy stop {price:.2f}')

    def _set_sell_stop(self):
        price = self._round_price(float(self.exec_data.close[0]) - self.p.indent_pips * self.p.point_size)
        self.pending_sell = self.sell(size=self.p.lots, exectype=bt.Order.Stop, price=price)
        self.log(f'set sell stop {price:.2f}')

    def next(self):
        self.bar_num += 1
        self._delete_far_pending()
        self._apply_trailing()
        if len(self.signal_data) < max(int(self.p.signal_bar), 1) + 2:
            return
        if self.position or self.pending_buy is not None or self.pending_sell is not None:
            return
        if not self._new_signal_bar():
            return
        recent_ago = max(int(self.p.signal_bar), 1) - 1
        prev_ago = max(int(self.p.signal_bar), 1)
        cci_now = float(self.signal_data.cci[-recent_ago]) if recent_ago else float(self.signal_data.cci[0])
        cci_prev = float(self.signal_data.cci[-prev_ago])
        if cci_now > -self.p.cci_max_min and cci_prev < -self.p.cci_max_min:
            self._set_buy_stop()
        elif cci_now < self.p.cci_max_min and cci_prev > self.p.cci_max_min:
            self._set_sell_stop()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if self._same_order(order, self.pending_buy):
            if order.status == order.Completed:
                self.buy_count += 1
                self.pending_buy = None
                if self.pending_sell is not None and self.pending_sell.alive():
                    self.cancel(self.pending_sell)
                    self.pending_sell = None
                if self.p.stoploss_pips > 0 and order.executed.size > 0:
                    stop_price = self._round_price(order.executed.price - self.p.stoploss_pips * self.p.point_size)
                    self._place_position_stop(stop_price)
                self.active_side = 'long'
                self.log(f'buy stop filled price={order.executed.price:.2f}')
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.pending_buy = None
            return
        if self._same_order(order, self.pending_sell):
            if order.status == order.Completed:
                self.sell_count += 1
                self.pending_sell = None
                if self.pending_buy is not None and self.pending_buy.alive():
                    self.cancel(self.pending_buy)
                    self.pending_buy = None
                if self.p.stoploss_pips > 0 and order.executed.size < 0:
                    stop_price = self._round_price(order.executed.price + self.p.stoploss_pips * self.p.point_size)
                    self._place_position_stop(stop_price)
                self.active_side = 'short'
                self.log(f'sell stop filled price={order.executed.price:.2f}')
            elif order.status in (order.Canceled, order.Margin, order.Rejected, order.Expired):
                self.pending_sell = None
            return
        if self._same_order(order, self.position_stop) and order.status == order.Completed:
            self.position_stop = None
            self.active_stop_price = None
            self.active_side = None
            self.stop_cancel_pending = False
            self.stop_replace_price = None
        elif self._same_order(order, self.position_stop) and order.status in (order.Canceled, order.Margin, order.Rejected):
            self.position_stop = None
            if order.status == order.Canceled and self.stop_cancel_pending and self.stop_replace_price is not None and self.position:
                self._place_position_stop(self.stop_replace_price)
            else:
                self.stop_cancel_pending = False
                self.stop_replace_price = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.active_side = None
        self.active_stop_price = None
        self.stop_cancel_pending = False
        self.stop_replace_price = None
        if not self.position:
            self.position_stop = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
