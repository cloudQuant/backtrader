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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class RelativeVigorIndex(bt.Indicator):
    lines = ('rvi', 'signal')
    params = dict(period=13)

    def __init__(self):
        weighted_num = (
            (self.data.close - self.data.open)
            + 2.0 * (self.data.close(-1) - self.data.open(-1))
            + 2.0 * (self.data.close(-2) - self.data.open(-2))
            + (self.data.close(-3) - self.data.open(-3))
        ) / 6.0
        weighted_den = (
            (self.data.high - self.data.low)
            + 2.0 * (self.data.high(-1) - self.data.low(-1))
            + 2.0 * (self.data.high(-2) - self.data.low(-2))
            + (self.data.high(-3) - self.data.low(-3))
        ) / 6.0
        num_ma = bt.indicators.SimpleMovingAverage(weighted_num, period=self.p.period)
        den_ma = bt.indicators.SimpleMovingAverage(weighted_den, period=self.p.period)
        self.lines.rvi = bt.If(den_ma != 0, num_ma / den_ma, 0.0)
        self.lines.signal = (
            self.lines.rvi
            + 2.0 * self.lines.rvi(-1)
            + 2.0 * self.lines.rvi(-2)
            + self.lines.rvi(-3)
        ) / 6.0


class Exp3RviStrategy(bt.Strategy):
    params = dict(
        lot=0.1,
        stop_loss=1000,
        take_profit=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close1=True,
        sell_pos_close1=True,
        buy_pos_close2=True,
        sell_pos_close2=True,
        buy_pos_close3=True,
        sell_pos_close3=True,
        rvi_period=13,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.data_tf1 = self.datas[0]
        self.data_tf2 = self.datas[1]
        self.data_tf3 = self.datas[2]
        self.rvi1 = RelativeVigorIndex(self.data_tf1, period=self.p.rvi_period)
        self.rvi2 = RelativeVigorIndex(self.data_tf2, period=self.p.rvi_period)
        self.rvi3 = RelativeVigorIndex(self.data_tf3, period=self.p.rvi_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data_tf3.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _trend_value(self, rvi, allow_buy, allow_sell):
        main = float(rvi.rvi[0])
        signal = float(rvi.signal[0])
        if main > signal and allow_buy:
            return 1
        if main < signal and allow_sell:
            return -1
        return 0

    def _cross_buy(self):
        return float(self.rvi3.rvi[0]) > float(self.rvi3.signal[0]) and float(self.rvi3.rvi[-1]) <= float(self.rvi3.signal[-1])

    def _cross_sell(self):
        return float(self.rvi3.rvi[0]) < float(self.rvi3.signal[0]) and float(self.rvi3.rvi[-1]) >= float(self.rvi3.signal[-1])

    def _set_risk_prices(self, is_long, price):
        self.stop_price = None
        self.take_profit_price = None
        if self.p.stop_loss > 0:
            self.stop_price = round(price - self.p.stop_loss * self.p.point, self.p.price_digits) if is_long else round(price + self.p.stop_loss * self.p.point, self.p.price_digits)
        if self.p.take_profit > 0:
            self.take_profit_price = round(price + self.p.take_profit * self.p.point, self.p.price_digits) if is_long else round(price - self.p.take_profit * self.p.point, self.p.price_digits)

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.rvi_period + 8, 25)
        if len(self.data_tf1) < warmup or len(self.data_tf2) < warmup or len(self.data_tf3) < warmup:
            return
        if self.entry_order is not None:
            return

        trend1 = self._trend_value(self.rvi1, self.p.buy_pos_open, self.p.sell_pos_open)
        trend2 = self._trend_value(self.rvi2, self.p.buy_pos_open, self.p.sell_pos_open)
        trend3 = self._trend_value(self.rvi3, self.p.buy_pos_open, self.p.sell_pos_open)
        buy_open = self.p.buy_pos_open and self._cross_buy() and trend1 > 0 and trend2 > 0
        sell_open = self.p.sell_pos_open and self._cross_sell() and trend1 < 0 and trend2 < 0
        buy_close = (trend1 < 0 and self.p.buy_pos_close1) or (trend2 < 0 and self.p.buy_pos_close2) or (trend3 < 0 and self.p.buy_pos_close3)
        sell_close = (trend1 > 0 and self.p.sell_pos_close1) or (trend2 > 0 and self.p.sell_pos_close2) or (trend3 > 0 and self.p.sell_pos_close3)

        close_price = round(float(self.data_tf3.close[0]), self.p.price_digits)
        high_price = round(float(self.data_tf3.high[0]), self.p.price_digits)
        low_price = round(float(self.data_tf3.low[0]), self.p.price_digits)

        if self.position:
            if self.position.size > 0:
                if self.stop_price is not None and low_price <= self.stop_price:
                    self.log(f'close long by stop={self.stop_price:.2f}')
                    self.entry_order = self.close()
                    return
                if self.take_profit_price is not None and high_price >= self.take_profit_price:
                    self.log(f'close long by take_profit={self.take_profit_price:.2f}')
                    self.entry_order = self.close()
                    return
                if buy_close:
                    self.log('close long by multi-timeframe trend')
                    self.entry_order = self.close()
                    return
            else:
                if self.stop_price is not None and high_price >= self.stop_price:
                    self.log(f'close short by stop={self.stop_price:.2f}')
                    self.entry_order = self.close()
                    return
                if self.take_profit_price is not None and low_price <= self.take_profit_price:
                    self.log(f'close short by take_profit={self.take_profit_price:.2f}')
                    self.entry_order = self.close()
                    return
                if sell_close:
                    self.log('close short by multi-timeframe trend')
                    self.entry_order = self.close()
                    return
            return

        if buy_open:
            self.log(f'buy trend1={trend1} trend2={trend2} rvi3={float(self.rvi3.rvi[0]):.4f} sig3={float(self.rvi3.signal[0]):.4f}')
            self._set_risk_prices(True, close_price)
            self.entry_order = self.buy(size=self.p.lot)
            return
        if sell_open:
            self.log(f'sell trend1={trend1} trend2={trend2} rvi3={float(self.rvi3.rvi[0]):.4f} sig3={float(self.rvi3.signal[0]):.4f}')
            self._set_risk_prices(False, close_price)
            self.entry_order = self.sell(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.log(f'entry filled price={order.executed.price:.2f} size={order.executed.size:.2f}')
            else:
                self.log(f'position closed price={order.executed.price:.2f} size={order.executed.size:.2f}')
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
