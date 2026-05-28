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


class FTBillWilliamsTraderStrategy(bt.Strategy):
    params = dict(
        count_bars_fractal=5,
        max_distance=1000,
        indent=1,
        type_entry=2,
        red_control=1,
        jaw_period=13,
        teeth_period=8,
        lips_period=5,
        trend_alig_control=0,
        jaw_teeth_distance=10,
        teeth_lips_distance=10,
        close_drop_teeth=2,
        close_revers_signal=2,
        stop_loss=50,
        take_profit=50,
        lots=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        median = (self.data.high + self.data.low) / 2.0
        self.jaw = bt.indicators.SmoothedMovingAverage(median, period=self.p.jaw_period)
        self.teeth = bt.indicators.SmoothedMovingAverage(median, period=self.p.teeth_period)
        self.lips = bt.indicators.SmoothedMovingAverage(median, period=self.p.lips_period)

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
        self.active_buy_level = None
        self.active_sell_level = None
        self.last_buy_fractal_index = None
        self.last_sell_fractal_index = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _set_risk(self, side, price=None):
        unit = self._unit()
        if price is None:
            price = float(self.data.close[0])
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits))
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits))

    def _is_buy_fractal(self):
        half = (int(self.p.count_bars_fractal) - 1) // 2
        idx = -half
        highs = [float(self.data.high[i]) for i in range(-2 * half, 1)]
        center = float(self.data.high[idx])
        return center == max(highs)

    def _is_sell_fractal(self):
        half = (int(self.p.count_bars_fractal) - 1) // 2
        idx = -half
        lows = [float(self.data.low[i]) for i in range(-2 * half, 1)]
        center = float(self.data.low[idx])
        return center == min(lows)

    def _max_distance_ok(self, entryprice):
        return abs(entryprice - float(self.lips[0])) <= float(self.p.max_distance) * self._unit()

    def _red_control_ok(self, entryprice, side):
        if int(self.p.red_control) == 0:
            return True
        teeth = float(self.teeth[0])
        if side == 'buy':
            return entryprice > teeth
        return entryprice < teeth

    def _trend_control_ok(self, side):
        if int(self.p.trend_alig_control) == 0:
            return True
        jaw = float(self.jaw[0])
        teeth = float(self.teeth[0])
        lips = float(self.lips[0])
        if side == 'buy':
            return (lips - teeth) > float(self.p.teeth_lips_distance) * self._unit() and (teeth - jaw) > float(self.p.jaw_teeth_distance) * self._unit()
        return (teeth - lips) > float(self.p.teeth_lips_distance) * self._unit() and (jaw - teeth) > float(self.p.jaw_teeth_distance) * self._unit()

    def _update_fractals(self):
        if len(self) < int(self.p.count_bars_fractal):
            return
        half = (int(self.p.count_bars_fractal) - 1) // 2
        center_index = len(self) - 1 - half
        indent = float(self.p.indent) * self._unit()
        if self._is_buy_fractal():
            level = round(float(self.data.high[-half]) + indent, int(self.p.price_digits))
            if self._red_control_ok(level, 'buy'):
                self.active_buy_level = level
                self.last_buy_fractal_index = center_index
        if self._is_sell_fractal():
            level = round(float(self.data.low[-half]) - indent, int(self.p.price_digits))
            if self._red_control_ok(level, 'sell'):
                self.active_sell_level = level
                self.last_sell_fractal_index = center_index

    def _buy_triggered(self):
        if self.active_buy_level is None:
            return False
        if not self._max_distance_ok(self.active_buy_level):
            return False
        if not self._trend_control_ok('buy'):
            return False
        if int(self.p.type_entry) == 1:
            return float(self.data.high[0]) > self.active_buy_level
        return float(self.data.close[0]) > self.active_buy_level

    def _sell_triggered(self):
        if self.active_sell_level is None:
            return False
        if not self._max_distance_ok(self.active_sell_level):
            return False
        if not self._trend_control_ok('sell'):
            return False
        if int(self.p.type_entry) == 1:
            return float(self.data.low[0]) < self.active_sell_level
        return float(self.data.close[0]) < self.active_sell_level

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        teeth = float(self.teeth[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
            if int(self.p.close_drop_teeth) == 2 and close < teeth:
                self.order = self.close()
                return True
            if int(self.p.close_revers_signal) == 2 and self._sell_triggered():
                self.order = self.close()
                return True
        else:
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
            if int(self.p.close_drop_teeth) == 2 and close > teeth:
                self.order = self.close()
                return True
            if int(self.p.close_revers_signal) == 2 and self._buy_triggered():
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < int(self.p.count_bars_fractal):
            return
        self._update_fractals()
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        if self._buy_triggered():
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.lots)
            self.active_buy_level = None
            return
        if self._sell_triggered():
            self.signal_count += 1
            self._set_risk('sell')
            self.order = self.sell(size=self.p.lots)
            self.active_sell_level = None

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
