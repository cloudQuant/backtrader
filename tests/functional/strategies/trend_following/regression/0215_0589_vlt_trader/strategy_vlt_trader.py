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


class VLTTraderStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        take_profit=10,
        stop_loss=10,
        size_candles=100,
        count_candles=6,
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
        self.pending_buy = None
        self.pending_sell = None
        self.stop_price = None
        self.take_profit_price = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _check_pending(self):
        if self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.pending_buy is not None and high >= float(self.pending_buy['entry']):
            self.stop_price = self.pending_buy['sl']
            self.take_profit_price = self.pending_buy['tp']
            self.signal_count += 1
            self.order = self.buy(size=self.p.lots)
            self.pending_buy = None
            self.pending_sell = None
            return
        if self.pending_sell is not None and low <= float(self.pending_sell['entry']):
            self.stop_price = self.pending_sell['sl']
            self.take_profit_price = self.pending_sell['tp']
            self.signal_count += 1
            self.order = self.sell(size=self.p.lots)
            self.pending_buy = None
            self.pending_sell = None

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
        if len(self) < int(self.p.count_candles) + 3:
            return
        if self.order is not None:
            return

        self._check_pending()
        if self.order is not None:
            return

        if self.position:
            self._check_exit()
            return

        high_0 = float(self.data.high[0])
        high_1 = float(self.data.high[-1])
        low_1 = float(self.data.low[-1])
        if high_0 > high_1:
            return

        vlt_1 = abs(high_1 - low_1)
        vlt_minimum = float('inf')
        limit_size = float(self.p.size_candles) * self._point()
        for i in range(2, 2 + int(self.p.count_candles)):
            size = abs(float(self.data.high[-i]) - float(self.data.low[-i]))
            if 0.0 < size < limit_size and size < vlt_minimum:
                vlt_minimum = size

        if vlt_minimum == float('inf'):
            return

        if vlt_1 < vlt_minimum:
            buy_entry = self._round(high_1 + 10 * self._point())
            sell_entry = self._round(low_1 - 10 * self._point())
            sl_dist = float(self.p.stop_loss) * self._point()
            tp_dist = float(self.p.take_profit) * self._point()
            self.pending_buy = {
                'entry': buy_entry,
                'sl': self._round(buy_entry - sl_dist) if sl_dist > 0 else None,
                'tp': self._round(buy_entry + tp_dist) if tp_dist > 0 else None,
            }
            self.pending_sell = {
                'entry': sell_entry,
                'sl': self._round(sell_entry + sl_dist) if sl_dist > 0 else None,
                'tp': self._round(sell_entry - tp_dist) if tp_dist > 0 else None,
            }

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
