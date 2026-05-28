from __future__ import absolute_import, division, print_function, unicode_literals

import io

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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume']
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TwentyOneHourStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        hour_start_first=8,
        hour_stop_first=21,
        hour_start_second=22,
        hour_stop_second=23,
        step=5,
        take_profit=40,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.order = None
        self.pending_buy_stop = None
        self.pending_sell_stop = None
        self.take_profit_buy = None
        self.take_profit_sell = None

    def _dt(self, idx=0):
        return bt.num2date(self.data.datetime[idx])

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _delete_orders(self):
        self.pending_buy_stop = None
        self.pending_sell_stop = None
        self.take_profit_buy = None
        self.take_profit_sell = None

    def _close_positions(self):
        if self.position and self.order is None:
            self.order = self.close()
        self._delete_orders()

    def _maybe_place_orders(self):
        dt = self._dt(0)
        if self.position or self.pending_buy_stop is not None or self.pending_sell_stop is not None:
            return
        if (dt.hour == int(self.p.hour_start_first) and dt.minute == 0) or (dt.hour == int(self.p.hour_start_second) and dt.minute == 0):
            price_buy = self._round(float(self.data.close[0]) + float(self.p.step) * self._point())
            price_sell = self._round(float(self.data.close[0]) - float(self.p.step) * self._point())
            self.pending_buy_stop = price_buy
            self.pending_sell_stop = price_sell
            self.take_profit_buy = self._round(price_buy + float(self.p.take_profit) * self._point())
            self.take_profit_sell = self._round(price_sell - float(self.p.take_profit) * self._point())

    def _maybe_end_window(self):
        dt = self._dt(0)
        if (dt.hour == int(self.p.hour_stop_first) and dt.minute == 0) or (dt.hour == int(self.p.hour_stop_second) and dt.minute == 0):
            self._close_positions()

    def _check_pending_triggers(self):
        if self.position:
            self._delete_orders()
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.pending_buy_stop is not None and high >= float(self.pending_buy_stop):
            self.signal_count += 1
            self.pending_sell_stop = None
            self.order = self.buy(size=self.p.lots)
            return
        if self.pending_sell_stop is not None and low <= float(self.pending_sell_stop):
            self.signal_count += 1
            self.pending_buy_stop = None
            self.order = self.sell(size=self.p.lots)

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0 and self.take_profit_buy is not None and high >= float(self.take_profit_buy):
            self.order = self.close()
            self._delete_orders()
            return
        if self.position.size < 0 and self.take_profit_sell is not None and low <= float(self.take_profit_sell):
            self.order = self.close()
            self._delete_orders()

    def next(self):
        self.bar_num += 1
        if len(self) < 2:
            return
        self._maybe_end_window()
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        self._maybe_place_orders()
        self._check_pending_triggers()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self._delete_orders()
            else:
                self._delete_orders()
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
