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


class CheduecoglioniStrategy(bt.Strategy):
    """Alternating direction strategy (EA 0601).

    After a position is closed (SL or TP hit), opens a new position
    in the opposite direction. Starts with a Sell.

    Logic:
      - Initial: open Sell with SL/TP.
      - When closed (deal_entry == OUT, deal_type == BUY) -> next = Sell.
      - When closed (deal_entry == OUT, deal_type == SELL) -> next = Buy.
      - Effectively alternates Buy/Sell after each close.
    """

    params = dict(
        lots=0.1,
        take_profit=10,
        stop_loss=10,
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
        self.stop_price = None
        self.take_profit_price = None
        self.next_direction = 'sell'
        self.need_open = True

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        if self.position:
            self._check_exit()
            return

        if self.need_open:
            self.signal_count += 1
            price = float(self.data.close[0])
            sl_dist = float(self.p.stop_loss) * self._point()
            tp_dist = float(self.p.take_profit) * self._point()

            if self.next_direction == 'buy':
                self.stop_price = self._round(price - sl_dist) if sl_dist > 0 else None
                self.take_profit_price = self._round(price + tp_dist) if tp_dist > 0 else None
                self.order = self.buy(size=self.p.lots)
            else:
                self.stop_price = self._round(price + sl_dist) if sl_dist > 0 else None
                self.take_profit_price = self._round(price - tp_dist) if tp_dist > 0 else None
                self.order = self.sell(size=self.p.lots)
            self.need_open = False

    def _check_exit(self):
        high = float(self.data.high[0])
        low = float(self.data.low[0])

        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        elif self.position.size < 0:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

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
        if self.next_direction == 'buy':
            self.next_direction = 'sell'
        else:
            self.next_direction = 'buy'
        self.need_open = True
