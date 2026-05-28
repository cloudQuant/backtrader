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


class BollingerBandsStrategy(bt.Strategy):
    params = dict(
        profit_made=3,
        loss_limit=20,
        bb_period=4,
        bb_deviation=2,
        b_distance=3,
        lots=1.0,
        lot_increase=True,
        starting_balance=1000,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        one_order_only=True,
    )

    def __init__(self):
        self.bbands = bt.indicators.BollingerBands(self.data.open, period=self.p.bb_period, devfactor=self.p.bb_deviation)

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

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _lots(self):
        if not self.p.lot_increase:
            return float(self.p.lots)
        ext_lots = round(float(self.broker.getvalue()) / float(self.p.starting_balance), 1)
        return min(ext_lots, 500.0)

    def _buy_signal(self):
        upper = float(self.bbands.top[0])
        close = float(self.data.close[0])
        return close < upper - 1e12 if False else close < float('-inf')

    def next(self):
        self.bar_num += 1
        if len(self) < self.p.bb_period + 2:
            return
        if self.order is not None:
            return
        upper = float(self.bbands.top[0])
        lower = float(self.bbands.bot[0])
        close = float(self.data.close[0])
        distance = float(self.p.b_distance) * self._unit()
        buy_me = close < (lower - distance)
        sell_me = close > (upper + distance)
        positions_per_symbol = 1 if self.position else 0
        current_profit = 0.0
        if self.position:
            if self.position.size > 0:
                current_profit = float(self.data.close[0]) - self.position.price
            else:
                current_profit = self.position.price - float(self.data.close[0])
            if self.p.profit_made > 0 and current_profit >= float(self.p.profit_made) * self._unit():
                self.order = self.close()
                return
            if self.p.loss_limit > 0 and current_profit <= -float(self.p.loss_limit) * self._unit():
                self.order = self.close()
                return
        if ((self.p.one_order_only and positions_per_symbol == 0 and buy_me) or ((not self.p.one_order_only) and buy_me)):
            self.signal_count += 1
            self.order = self.buy(size=self._lots())
            return
        if ((self.p.one_order_only and positions_per_symbol == 0 and sell_me) or ((not self.p.one_order_only) and sell_me)):
            self.signal_count += 1
            self.order = self.sell(size=self._lots())

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
