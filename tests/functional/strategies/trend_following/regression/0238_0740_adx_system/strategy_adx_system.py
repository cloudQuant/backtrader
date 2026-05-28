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


class ADXSystemStrategy(bt.Strategy):
    params = dict(
        take_profit=15,
        lots=1.0,
        trailing_stop=20,
        stop_loss=100,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        adx_period=14,
    )

    def __init__(self):
        self.dmi = bt.indicators.DirectionalMovementIndex(self.data, period=self.p.adx_period)
        self.adx = self.dmi.adx
        self.plus_di = self.dmi.plusDI
        self.minus_di = self.dmi.minusDI

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

    def _set_risk(self, side):
        unit = self._unit()
        price = float(self.data.close[0])
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits))
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits))

    def _trail(self):
        if not self.position or self.p.trailing_stop <= 0:
            return
        unit = self._unit()
        price = float(self.data.close[0])
        if self.position.size > 0 and price - self.position.price > float(self.p.trailing_stop) * unit:
            new_stop = round(price - float(self.p.trailing_stop) * unit, int(self.p.price_digits))
            if self.stop_price is None or self.stop_price < new_stop:
                self.stop_price = new_stop
        if self.position.size < 0 and self.position.price - price > float(self.p.trailing_stop) * unit:
            new_stop = round(price + float(self.p.trailing_stop) * unit, int(self.p.price_digits))
            if self.stop_price is None or self.stop_price > new_stop:
                self.stop_price = new_stop

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        adxp = float(self.adx[-2])
        adxc = float(self.adx[-1])
        plus_p = float(self.plus_di[-2])
        plus_c = float(self.plus_di[-1])
        minus_p = float(self.minus_di[-2])
        minus_c = float(self.minus_di[-1])
        if self.position.size > 0 and adxp > adxc and plus_p > adxp and plus_c < adxc:
            self.order = self.close()
            return True
        if self.position.size < 0 and adxp > adxc and minus_p > adxp and minus_c < adxc:
            self.order = self.close()
            return True
        self._trail()
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if low <= self.stop_price or high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if high >= self.stop_price or low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < self.p.adx_period + 3:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        adxp = float(self.adx[-2])
        adxc = float(self.adx[-1])
        plus_p = float(self.plus_di[-2])
        plus_c = float(self.plus_di[-1])
        minus_p = float(self.minus_di[-2])
        minus_c = float(self.minus_di[-1])
        if (adxp < adxc) and (plus_p < adxp) and (plus_c > adxc):
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.lots)
            return
        if (adxp < adxc) and (minus_p < adxp) and (minus_c > adxc):
            self.signal_count += 1
            self._set_risk('sell')
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
