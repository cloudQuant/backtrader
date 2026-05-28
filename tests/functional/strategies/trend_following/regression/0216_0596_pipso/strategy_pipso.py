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


class PipsoStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        start_hour=21,
        end_hour=9,
        period=36,
        slpp=300.0,
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

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _in_window(self):
        hour = self.data.datetime.datetime(0).hour
        start = int(self.p.start_hour)
        end = int(self.p.end_hour)
        if start < end:
            return start <= hour <= end
        return hour >= start or hour <= end

    def _highest(self):
        values = [float(self.data.high[-i]) for i in range(1, int(self.p.period) + 1)]
        return max(values)

    def _lowest(self):
        values = [float(self.data.low[-i]) for i in range(1, int(self.p.period) + 1)]
        return min(values)

    def _check_exit(self):
        if not self.position or self.order is not None or self.stop_price is None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0 and low <= float(self.stop_price):
            self.pending_direction = None
            self.order = self.close()
            return
        if self.position.size < 0 and high >= float(self.stop_price):
            self.pending_direction = None
            self.order = self.close()

    def next(self):
        self.bar_num += 1
        if len(self) < int(self.p.period) + 2:
            return
        if self.order is not None:
            return

        if not self.position and self.pending_direction is not None:
            if self.pending_direction == 'buy':
                self.signal_count += 1
                self.order = self.buy(size=self.p.lots)
            else:
                self.signal_count += 1
                self.order = self.sell(size=self.p.lots)
            self.pending_direction = None
            return

        if self.position:
            self._check_exit()
            if self.order is not None:
                return

        high_level = self._highest()
        low_level = self._lowest()
        width = (high_level - low_level) * (float(self.p.slpp) / 100.0 + 1.0)
        bid = float(self.data.close[0])

        if bid >= high_level:
            if self.position.size > 0:
                self.pending_direction = 'sell'
                self.order = self.close()
                return
            if self._in_window() and self.position.size == 0:
                self.stop_price = self._round(bid + width)
                self.signal_count += 1
                self.order = self.sell(size=self.p.lots)
                return

        if bid <= low_level:
            if self.position.size < 0:
                self.pending_direction = 'buy'
                self.order = self.close()
                return
            if self._in_window() and self.position.size == 0:
                self.stop_price = self._round(bid - width)
                self.signal_count += 1
                self.order = self.buy(size=self.p.lots)

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
