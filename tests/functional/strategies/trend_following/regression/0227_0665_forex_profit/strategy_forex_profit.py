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


class ForexProfitStrategy(bt.Strategy):
    params = dict(
        take_profit_buy=55,
        take_profit_sell=65,
        stop_loss_buy=60,
        stop_loss_sell=85,
        trailing_stop_buy=20,
        trailing_step=5,
        trailing_stop_sell=74,
        lots=1.0,
        ema10_period=10,
        ema25_period=25,
        ema50_period=50,
        sar_af=0.02,
        sar_afmax=0.2,
        point=0.01,
        price_digits=2,
        contract_multiplier=100.0,
        min_profit_to_exit=10.0,
    )

    def __init__(self):
        median = (self.data.high + self.data.low) / 2.0
        self.ema10 = bt.indicators.ExponentialMovingAverage(median, period=self.p.ema10_period)
        self.ema25 = bt.indicators.ExponentialMovingAverage(median, period=self.p.ema25_period)
        self.ema50 = bt.indicators.ExponentialMovingAverage(median, period=self.p.ema50_period)
        self.sar = bt.indicators.ParabolicSAR(self.data, af=self.p.sar_af, afmax=self.p.sar_afmax)

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

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _floating_pnl(self):
        if not self.position:
            return 0.0
        return (float(self.data.close[0]) - float(self.position.price)) * float(self.position.size) * float(self.p.contract_multiplier)

    def _set_risk(self, side, price):
        if side == 'buy':
            self.stop_price = self._round(price - float(self.p.stop_loss_buy) * self._point())
            self.take_profit_price = self._round(price + float(self.p.take_profit_buy) * self._point())
        else:
            self.stop_price = self._round(price + float(self.p.stop_loss_sell) * self._point())
            self.take_profit_price = self._round(price - float(self.p.take_profit_sell) * self._point())

    def _buy_signal(self):
        return float(self.ema10[0]) > float(self.ema25[0]) and float(self.ema10[0]) > float(self.ema50[0]) and float(self.ema10[-1]) <= float(self.ema50[-1]) and float(self.sar[-1]) < float(self.data.close[-1])

    def _sell_signal(self):
        return float(self.ema10[0]) < float(self.ema25[0]) and float(self.ema10[0]) < float(self.ema50[0]) and float(self.ema10[-1]) >= float(self.ema50[-1]) and float(self.sar[-1]) > float(self.data.close[-1])

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        ema10_now = float(self.ema10[0])
        ema10_prev = float(self.ema10[-1])
        pnl = self._floating_pnl()
        if self.position.size > 0:
            if ema10_now < ema10_prev and pnl > float(self.p.min_profit_to_exit):
                self.order = self.close()
                return
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
            if float(self.p.trailing_stop_buy) > 0:
                move_trigger = float(self.p.trailing_stop_buy) * self._point()
                if float(self.data.close[0]) - float(self.position.price) > move_trigger:
                    candidate = self._round(float(self.data.close[0]) - move_trigger)
                    threshold = self._round(float(self.data.close[0]) - (float(self.p.trailing_stop_buy) + float(self.p.trailing_step)) * self._point())
                    if self.stop_price is None or float(self.stop_price) < threshold:
                        self.stop_price = candidate
        else:
            if ema10_now > ema10_prev and pnl > float(self.p.min_profit_to_exit):
                self.order = self.close()
                return
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return
            if float(self.p.trailing_stop_sell) > 0:
                move_trigger = float(self.p.trailing_stop_sell) * self._point()
                if float(self.position.price) - float(self.data.close[0]) > move_trigger:
                    candidate = self._round(float(self.data.close[0]) + move_trigger)
                    threshold = self._round(float(self.data.close[0]) + (float(self.p.trailing_stop_sell) + float(self.p.trailing_step)) * self._point())
                    if self.stop_price is None or float(self.stop_price) > threshold:
                        self.stop_price = candidate

    def next(self):
        self.bar_num += 1
        if len(self) < self.p.ema50_period + 2:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        signal = 0
        if self._buy_signal():
            signal = 1
        elif self._sell_signal():
            signal = -1
        if signal == 0:
            return
        self.signal_count += 1
        price = float(self.data.close[0])
        if signal > 0:
            self._set_risk('buy', price)
            self.order = self.buy(size=self.p.lots)
        else:
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
