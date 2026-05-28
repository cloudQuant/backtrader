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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


class EurUsdBreakoutStrategy(bt.Strategy):
    params = dict(
        start_hour_eu_session=5,
        start_hour_us_session=2,
        end_hour_us_session=16,
        small_eu_session_pips=72,
        trade_on_monday=False,
        lots=1.0,
        stop_loss=12,
        take_profit=15,
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
        self.pending_direction = None
        self.stop_price = None
        self.take_profit_price = None
        self.day_key = None
        self.top_range = None
        self.low_range = None
        self.bought = False
        self.sold = False
        self.small_session = False
        self.session_found = False

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _reset_day(self, day_key):
        self.day_key = day_key
        self.top_range = None
        self.low_range = None
        self.bought = False
        self.sold = False
        self.small_session = False
        self.session_found = False

    def _calc_eu_range(self):
        if len(self) < 25:
            return None, None
        highs = [float(self.data.high[-i]) for i in range(1, 25)]
        lows = [float(self.data.low[-i]) for i in range(1, 25)]
        return max(highs), min(lows)

    def _arm(self, direction, price):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if direction == 'buy':
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
            self.signal_count += 1
            self.order = self.buy(size=float(self.p.lots))
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None
            self.signal_count += 1
            self.order = self.sell(size=float(self.p.lots))

    def _check_exit(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        dt = self.data.datetime.datetime(0)
        if self.day_key != dt.date().isoformat():
            self._reset_day(dt.date().isoformat())

        if dt.weekday() >= 5:
            return
        if dt.weekday() == 0 and not self.p.trade_on_monday:
            return
        if self.order is not None:
            return

        if not self.position and self.pending_direction is not None:
            self._arm(self.pending_direction, float(self.data.close[0]))
            self.pending_direction = None
            return

        if self.position:
            self._check_exit()
            if self.order is not None:
                return

        if not self.session_found and dt.hour == int(self.p.start_hour_us_session):
            top, low = self._calc_eu_range()
            if top is None or low is None:
                return
            self.top_range = top
            self.low_range = low
            self.small_session = (top - low) <= float(self.p.small_eu_session_pips) * self._point()
            self.session_found = True

        if not self.session_found or not self.small_session:
            return
        if not (int(self.p.start_hour_us_session) <= dt.hour < int(self.p.end_hour_us_session)):
            return
        if not (dt.hour > int(self.p.start_hour_eu_session) + 5 and dt.hour < int(self.p.start_hour_eu_session) + 10):
            return
        if len(self) < 2:
            return

        low_prev = float(self.data.low[-1])
        high_prev = float(self.data.high[-1])
        if (not self.bought) and self.top_range is not None and low_prev > self.top_range + 3 * self._point():
            if self.position.size < 0:
                self.pending_direction = 'buy'
                self.order = self.close()
            elif not self.position:
                self._arm('buy', float(self.data.close[0]))
            self.bought = True
            return
        if (not self.sold) and self.low_range is not None and high_prev < self.low_range - 3 * self._point():
            if self.position.size > 0:
                self.pending_direction = 'sell'
                self.order = self.close()
            elif not self.position:
                self._arm('sell', float(self.data.close[0]))
            self.sold = True

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
            else:
                self.stop_price = None
                self.take_profit_price = None
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
