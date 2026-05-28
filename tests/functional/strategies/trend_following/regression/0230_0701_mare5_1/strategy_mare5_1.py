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


class Mare51Strategy(bt.Strategy):
    params = dict(
        lots=0.01,
        take_profit=35.0,
        stop_loss=55.0,
        ma_fast_period=14,
        ma_slow_period=79,
        moving_shift=4,
        hour_time_open=2,
        hour_time_close=3,
        point=0.0001,
        digits_adjust=1,
        price_digits=5,
    )

    def __init__(self):
        self.ma_fast = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.ma_fast_period)
        self.ma_slow = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.ma_slow_period)

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

    def _shifted(self, line, bars_back):
        idx = -(bars_back + int(self.p.moving_shift))
        return float(line[idx])

    def _sell_signal(self):
        fast0 = self._shifted(self.ma_fast, 0)
        fast2 = self._shifted(self.ma_fast, 2)
        fast5 = self._shifted(self.ma_fast, 5)
        slow0 = self._shifted(self.ma_slow, 0)
        slow2 = self._shifted(self.ma_slow, 2)
        slow5 = self._shifted(self.ma_slow, 5)
        return (slow0 - fast0) >= self._unit() and (fast2 - slow2) >= self._unit() and (fast5 - slow5) >= self._unit() and float(self.data.close[-1]) < float(self.data.open[-1])

    def _buy_signal(self):
        fast0 = self._shifted(self.ma_fast, 0)
        fast2 = self._shifted(self.ma_fast, 2)
        fast5 = self._shifted(self.ma_fast, 5)
        slow0 = self._shifted(self.ma_slow, 0)
        slow2 = self._shifted(self.ma_slow, 2)
        slow5 = self._shifted(self.ma_slow, 5)
        return (fast0 - slow0) >= self._unit() and (slow2 - fast2) >= self._unit() and (slow5 - fast5) >= self._unit() and float(self.data.close[-1]) > float(self.data.open[-1])

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
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if high >= float(self.take_profit_price) or low <= float(self.stop_price):
                self.order = self.close()
                return True
        else:
            if low <= float(self.take_profit_price) or high >= float(self.stop_price):
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < self.p.ma_slow_period + self.p.moving_shift + 6:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        hour = bt.num2date(self.data.datetime[0]).hour
        if not (int(self.p.hour_time_open) <= hour <= int(self.p.hour_time_close)):
            return
        price = float(self.data.close[0])
        if self._sell_signal():
            self.signal_count += 1
            self._set_risk('sell', price)
            self.order = self.sell(size=self.p.lots)
            return
        if self._buy_signal():
            self.signal_count += 1
            self._set_risk('buy', price)
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
