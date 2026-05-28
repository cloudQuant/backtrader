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


def resample_daily(df):
    out = df.resample('1D', label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class Up3x1PremiumV2MStrategy(bt.Strategy):
    params = dict(
        lots=0.05,
        maximum_risk=0.1,
        decrease_factor=3.0,
        take_profit=150.0,
        stop_loss=100.0,
        trailing_stop=10.0,
        ma_period_one=12,
        ma_period_two=26,
        ma_period_day=10,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.daily = self.datas[1]
        self.ma_one = bt.indicators.ExponentialMovingAverage(self.base.close, period=self.p.ma_period_one)
        self.ma_two = bt.indicators.ExponentialMovingAverage(self.base.close, period=self.p.ma_period_two)
        self.ma_day = bt.indicators.ExponentialMovingAverage(self.daily.close, period=self.p.ma_period_day)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.losses = 0

        self.order = None
        self.stop_price = None
        self.take_profit_price = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _lots_optimized(self):
        lot = self.broker.getcash() * float(self.p.maximum_risk) / 1000.0
        if float(self.p.decrease_factor) > 0 and self.losses > 1:
            lot = lot - lot * self.losses / float(self.p.decrease_factor)
        if lot <= 0:
            lot = float(self.p.lots)
        return max(float(self.p.lots), round(lot, 2))

    def _buy_open_signal(self):
        if len(self.daily) < 2:
            return False
        ma_one_2 = float(self.ma_one[-2])
        ma_one_1 = float(self.ma_one[-1])
        ma_two_2 = float(self.ma_two[-2])
        ma_two_1 = float(self.ma_two[-1])
        high_1 = float(self.base.high[-1])
        low_1 = float(self.base.low[-1])
        open_1 = float(self.base.open[-1])
        close_1 = float(self.base.close[-1])
        open_2 = float(self.base.open[-2])
        open_day_1 = float(self.daily.open[-1])
        close_day_1 = float(self.daily.close[-1])
        ma_day_0 = float(self.ma_day[0])
        hour = bt.num2date(self.base.datetime[0]).hour
        return ((ma_one_2 < ma_two_2 and ma_two_1 < ma_one_1 and open_2 < open_1) or (high_1 - low_1 > 0.0060 and open_1 < close_1 and close_1 - open_1 > 0.0050) or (hour == 0 and open_day_1 > close_day_1 and open_day_1 - close_day_1 > 0.0060) or (ma_day_0 >= float(self.base.close[0]) or ma_day_0 <= float(self.base.close[0])))

    def _sell_open_signal(self):
        if len(self.daily) < 2:
            return False
        ma_one_2 = float(self.ma_one[-2])
        ma_one_1 = float(self.ma_one[-1])
        ma_two_2 = float(self.ma_two[-2])
        ma_two_1 = float(self.ma_two[-1])
        high_1 = float(self.base.high[-1])
        low_1 = float(self.base.low[-1])
        open_1 = float(self.base.open[-1])
        close_1 = float(self.base.close[-1])
        open_2 = float(self.base.open[-2])
        open_day_1 = float(self.daily.open[-1])
        close_day_1 = float(self.daily.close[-1])
        hour = bt.num2date(self.base.datetime[0]).hour
        return ((ma_one_2 > ma_two_2 and ma_two_1 > ma_one_1 and open_2 > open_1) or (high_1 - low_1 > 0.0060 and open_1 > close_1 and open_1 - close_1 > 0.0050) or (hour == 0 and open_day_1 < close_day_1 and close_day_1 - open_day_1 > 0.0060))

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
        ma_one_1 = float(self.ma_one[-1])
        ma_two_1 = float(self.ma_two[-1])
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        close = float(self.base.close[0])
        unit = self._unit()
        if ma_one_1 > ma_two_1 * 0.999 and ma_one_1 < ma_two_1 * 1.001:
            self.order = self.close()
            return True
        if self.position.size > 0:
            if high >= float(self.take_profit_price) or low <= float(self.stop_price):
                self.order = self.close()
                return True
            if float(self.p.trailing_stop) > 0 and close - float(self.position.price) > float(self.p.trailing_stop) * unit:
                candidate = round(close - float(self.p.trailing_stop) * unit, int(self.p.price_digits))
                if candidate > float(self.stop_price):
                    self.stop_price = candidate
        else:
            if low <= float(self.take_profit_price) or high >= float(self.stop_price):
                self.order = self.close()
                return True
            if float(self.p.trailing_stop) > 0 and float(self.position.price) - close > float(self.p.trailing_stop) * unit:
                candidate = round(close + float(self.p.trailing_stop) * unit, int(self.p.price_digits))
                if candidate < float(self.stop_price):
                    self.stop_price = candidate
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < max(self.p.ma_period_two, 30) or len(self.daily) < max(self.p.ma_period_day, 3):
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        lots = self._lots_optimized()
        price = float(self.base.close[0])
        if self._buy_open_signal():
            self.signal_count += 1
            self._set_risk('buy', price)
            self.order = self.buy(size=lots)
            return
        if self._sell_open_signal():
            self.signal_count += 1
            self._set_risk('sell', price)
            self.order = self.sell(size=lots)

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
            self.losses += 1
