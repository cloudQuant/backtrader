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


class MovingAverageTradeSystemStrategy(bt.Strategy):
    params = dict(
        take_profit=50,
        stop_loss=50,
        trailing_stop=11,
        lots=0.1,
        point=0.0001,
        digits_adjust=1,
        price_digits=5,
    )

    def __init__(self):
        median = (self.data.high + self.data.low) / 2.0
        self.sma5 = bt.indicators.SimpleMovingAverage(median, period=5)
        self.sma20 = bt.indicators.SimpleMovingAverage(median, period=20)
        self.sma40 = bt.indicators.SimpleMovingAverage(median, period=40)
        self.sma60 = bt.indicators.SimpleMovingAverage(median, period=60)

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

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _buy_signal(self):
        sma5 = float(self.sma5[-1])
        sma20 = float(self.sma20[-1])
        sma40_prev = float(self.sma40[-2])
        sma40 = float(self.sma40[-1])
        sma60 = float(self.sma60[-1])
        return sma5 > sma20 > sma40 and (sma40 - sma60) >= 0.0001 and sma40_prev <= sma60

    def _sell_signal(self):
        sma5 = float(self.sma5[-1])
        sma20 = float(self.sma20[-1])
        sma40_prev = float(self.sma40[-2])
        sma40 = float(self.sma40[-1])
        sma60 = float(self.sma60[-1])
        return sma5 < sma20 < sma40 and (sma60 - sma40) >= 0.0001 and sma40_prev >= sma60

    def _set_risk(self, side, price):
        unit = self._unit()
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits))
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits))

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        sma40 = float(self.sma40[-1])
        sma60 = float(self.sma60[-1])
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        unit = self._unit()
        if self.position.size > 0:
            if sma40 <= sma60 or high >= float(self.take_profit_price) or low <= float(self.stop_price):
                self.order = self.close()
                return True
            if float(self.p.trailing_stop) > 0 and close - float(self.position.price) > float(self.p.trailing_stop) * unit:
                candidate = round(close - float(self.p.trailing_stop) * unit, int(self.p.price_digits))
                if candidate > float(self.stop_price):
                    self.stop_price = candidate
        else:
            if sma40 >= sma60 or low <= float(self.take_profit_price) or high >= float(self.stop_price):
                self.order = self.close()
                return True
            if float(self.p.trailing_stop) > 0 and float(self.position.price) - close > float(self.p.trailing_stop) * unit:
                candidate = round(close + float(self.p.trailing_stop) * unit, int(self.p.price_digits))
                if candidate < float(self.stop_price):
                    self.stop_price = candidate
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < 65:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        price = float(self.data.close[0])
        if self._buy_signal():
            self.signal_count += 1
            self._set_risk('buy', price)
            self.order = self.buy(size=self.p.lots)
            return
        if self._sell_signal():
            self.signal_count += 1
            self._set_risk('sell', price)
            self.order = self.sell(size=self.p.lots)

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
