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


class BigDogStrategy(bt.Strategy):
    params = dict(
        start_hour=14,
        stop_hour=16,
        max_point=50,
        take_profit=50,
        lots=0.1,
        distance_max_min=20,
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
        self.pending_day = None
        self.stop_price = None
        self.take_profit_price = None

    def _dt(self, idx=0):
        return bt.num2date(self.data.datetime[idx])

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _clear_pending(self):
        self.pending_buy_stop = None
        self.pending_sell_stop = None
        self.pending_day = None

    def _range_high_low(self):
        current_day = self._dt(0).date()
        highs = []
        lows = []
        for i in range(len(self.data) - 1, -1, -1):
            dt = self._dt(-i)
            if dt.date() != current_day:
                continue
            if int(self.p.start_hour) <= dt.hour < int(self.p.stop_hour):
                highs.append(float(self.data.high[-i]))
                lows.append(float(self.data.low[-i]))
        if not highs or not lows:
            return None, None
        return max(highs), min(lows)

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                self._clear_pending()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                self._clear_pending()
                return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                self._clear_pending()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                self._clear_pending()
                return

    def _maybe_delete_old_pending(self):
        if self.pending_day is None:
            return
        if self._dt(0).date() != self.pending_day:
            self._clear_pending()

    def _place_pending_orders(self):
        if self.position or self.pending_buy_stop is not None or self.pending_sell_stop is not None:
            return
        dt_prev = self._dt(-1) if len(self.data) > 1 else self._dt(0)
        if dt_prev.hour < int(self.p.stop_hour):
            return
        high, low = self._range_high_low()
        if high is None or low is None:
            return
        if abs(high - low) >= float(self.p.max_point) * self._point():
            return
        price = float(self.data.close[0])
        self.pending_day = self._dt(0).date()
        if (high - price) > float(self.p.distance_max_min) * self._point():
            self.pending_buy_stop = self._round(high)
        if (price - low) > float(self.p.distance_max_min) * self._point():
            self.pending_sell_stop = self._round(low)

    def _check_pending_triggers(self):
        if self.position:
            self._clear_pending()
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.pending_buy_stop is not None and high >= float(self.pending_buy_stop):
            self.signal_count += 1
            self.stop_price = self._round(float(self.pending_sell_stop) if self.pending_sell_stop is not None else low)
            self.take_profit_price = self._round(float(self.pending_buy_stop) + float(self.p.take_profit) * self._point())
            self.pending_sell_stop = None
            self.order = self.buy(size=self.p.lots)
            return
        if self.pending_sell_stop is not None and low <= float(self.pending_sell_stop):
            self.signal_count += 1
            self.stop_price = self._round(float(self.pending_buy_stop) if self.pending_buy_stop is not None else high)
            self.take_profit_price = self._round(float(self.pending_sell_stop) - float(self.p.take_profit) * self._point())
            self.pending_buy_stop = None
            self.order = self.sell(size=self.p.lots)

    def next(self):
        self.bar_num += 1
        if len(self) < 10:
            return
        if self.order is not None:
            return
        self._manage_position()
        if self.position:
            return
        self._maybe_delete_old_pending()
        self._place_pending_orders()
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
                self._clear_pending()
            else:
                self.stop_price = None
                self.take_profit_price = None
                self._clear_pending()
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
