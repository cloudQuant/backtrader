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


class BollTradeStrategy(bt.Strategy):
    params = dict(
        take_profit=3,
        stop_loss=20,
        bdistance=3.0,
        bperiod=4,
        deviation=2.0,
        lots=1.0,
        lot_increase=True,
        one_position_only=True,
        point=0.0001,
        digits_adjust=1,
        price_digits=5,
    )

    def __init__(self):
        self.bands = bt.indicators.BollingerBands(self.data.open, period=self.p.bperiod, devfactor=self.p.deviation)
        self.starting_balance = None

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

    def start(self):
        self.starting_balance = self.broker.getvalue()

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _ext_lots(self):
        if not self.p.lot_increase or not self.starting_balance:
            return float(self.p.lots)
        ext = float(self.p.lots) * self.broker.getvalue() / self.starting_balance
        return max(0.01, round(ext, 2))

    def _set_risk(self, side, price):
        unit = self._unit()
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits)) if int(self.p.stop_loss) else None
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if int(self.p.take_profit) else None
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits)) if int(self.p.stop_loss) else None
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits)) if int(self.p.take_profit) else None

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if (self.take_profit_price is not None and high >= self.take_profit_price) or (self.stop_price is not None and low <= self.stop_price):
                self.order = self.close()
                return True
        else:
            if (self.take_profit_price is not None and low <= self.take_profit_price) or (self.stop_price is not None and high >= self.stop_price):
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < max(self.p.bperiod, 10):
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            if self.p.one_position_only:
                return
        bup = float(self.bands.top[0])
        bdn = float(self.bands.bot[0])
        close = float(self.data.close[0])
        unit = self._unit()
        buy_me = close < bdn - float(self.p.bdistance) * unit
        sell_me = close > bup + float(self.p.bdistance) * unit
        if self.p.one_position_only and self.position:
            return
        lots = self._ext_lots()
        if buy_me:
            self.signal_count += 1
            self._set_risk('buy', close)
            self.order = self.buy(size=lots)
            return
        if sell_me:
            self.signal_count += 1
            self._set_risk('sell', close)
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
