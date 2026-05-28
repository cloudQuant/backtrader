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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
    })
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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class PriceExtremeChannel(bt.Indicator):
    lines = ('upper', 'lower')
    params = dict(multiplier=5)

    def __init__(self):
        period = max(int(self.p.multiplier), 1)
        self.lines.upper = bt.indicators.Highest(self.data.high(-1), period=period)
        self.lines.lower = bt.indicators.Lowest(self.data.low(-1), period=period)
        self.addminperiod(period + 2)


class PriceExtremeIndicatorStrategy(bt.Strategy):
    params = dict(
        multiplier=5,
        signal_bar=1,
        enable_buy=True,
        enable_sell=True,
        reverse_trade=False,
        volume=0.1,
        stop_loss_points=0,
        take_profit_points=0,
        point=0.01,
    )

    def __init__(self):
        self.channel = PriceExtremeChannel(self.data, multiplier=self.p.multiplier)
        self.order = None
        self.pending_reentry = 0
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.stop_price = None
        self.take_profit_price = None

    def _clear_risk_levels(self):
        self.stop_price = None
        self.take_profit_price = None

    def _set_risk_levels(self, price, direction):
        stop_distance = self.p.stop_loss_points * self.p.point
        take_distance = self.p.take_profit_points * self.p.point
        if direction > 0:
            self.stop_price = price - stop_distance if stop_distance > 0 else None
            self.take_profit_price = price + take_distance if take_distance > 0 else None
        else:
            self.stop_price = price + stop_distance if stop_distance > 0 else None
            self.take_profit_price = price - take_distance if take_distance > 0 else None

    def _check_stops(self):
        if not self.position:
            self._clear_risk_levels()
            return False
        if self.position.size > 0:
            if self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and float(self.data.high[0]) >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and float(self.data.low[0]) <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def _build_signal(self):
        idx = -int(self.p.signal_bar)
        close_v = float(self.data.close[idx])
        upper_v = float(self.channel.upper[idx])
        lower_v = float(self.channel.lower[idx])
        open_long = close_v > upper_v
        open_short = close_v < lower_v
        if self.p.reverse_trade:
            open_long, open_short = open_short, open_long
        if not self.p.enable_buy:
            open_long = False
        if not self.p.enable_sell:
            open_short = False
        return open_long, open_short

    def next(self):
        self.bar_num += 1
        if len(self.data) <= self.p.multiplier + self.p.signal_bar + 1:
            return
        if self.order:
            return
        if self._check_stops():
            return

        if self.pending_reentry != 0 and not self.position:
            if self.pending_reentry > 0:
                self.order = self.buy(size=self.p.volume)
            else:
                self.order = self.sell(size=self.p.volume)
            self.pending_reentry = 0
            return

        open_long, open_short = self._build_signal()
        if open_long:
            if self.position.size < 0:
                self.pending_reentry = 1
                self.order = self.close()
                return
            self.order = self.buy(size=self.p.volume)
            return
        if open_short:
            if self.position.size > 0:
                self.pending_reentry = -1
                self.order = self.close()
                return
            self.order = self.sell(size=self.p.volume)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and order.executed.size > 0:
                self.buy_count += 1
                if self.position.size > 0:
                    self._set_risk_levels(order.executed.price, 1)
            elif order.issell() and order.executed.size < 0:
                self.sell_count += 1
                if self.position.size < 0:
                    self._set_risk_levels(order.executed.price, -1)
            elif self.position.size == 0:
                self._clear_risk_levels()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self._clear_risk_levels()
