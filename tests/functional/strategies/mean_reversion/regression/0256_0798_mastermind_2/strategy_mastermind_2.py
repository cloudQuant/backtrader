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


class MasterMind2Strategy(bt.Strategy):
    params = dict(
        lots=0.1,
        stop_loss=500,
        take_profit=500,
        trailing_stop=50,
        trailing_step=100,
        break_even=150,
        stochastic_period=100,
        stochastic_period_d=3,
        stochastic_period_slow=3,
        wpr_period=100,
        stoch_buy_level=3.0,
        stoch_sell_level=97.0,
        wpr_buy_level=-99.9,
        wpr_sell_level=-0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.stoch = bt.indicators.StochasticFull(
            self.data,
            period=self.p.stochastic_period,
            period_dfast=self.p.stochastic_period_d,
            period_dslow=self.p.stochastic_period_slow,
            movav=bt.indicators.SmoothedMovingAverage,
        )
        self.wpr = bt.indicators.WilliamsR(self.data, period=self.p.wpr_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.entry_price = None
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _buy_signal(self):
        return float(self.stoch.percD[0]) < self.p.stoch_buy_level and float(self.wpr[-1]) < self.p.wpr_buy_level

    def _sell_signal(self):
        return float(self.stoch.percD[0]) > self.p.stoch_sell_level and float(self.wpr[-1]) > self.p.wpr_sell_level

    def _update_risk_prices(self, close_price):
        if not self.position or self.entry_price is None:
            return
        if self.position.size > 0:
            if self.p.break_even > 0 and close_price - self.entry_price > self.p.break_even * self.p.point:
                if self.stop_price is None or self.stop_price < self.entry_price:
                    self.stop_price = round(self.entry_price, self.p.price_digits)
            if self.p.trailing_stop > 0 and close_price - self.entry_price > self.p.trailing_stop * self.p.point:
                candidate = round(close_price - self.p.trailing_stop * self.p.point, self.p.price_digits)
                threshold = close_price - (self.p.trailing_stop + self.p.trailing_step - 1) * self.p.point
                if self.stop_price is None or self.stop_price < round(threshold, self.p.price_digits):
                    self.stop_price = candidate
        else:
            if self.p.break_even > 0 and self.entry_price - close_price > self.p.break_even * self.p.point:
                if self.stop_price is None or self.stop_price > self.entry_price:
                    self.stop_price = round(self.entry_price, self.p.price_digits)
            if self.p.trailing_stop > 0 and self.entry_price - close_price > self.p.trailing_stop * self.p.point:
                candidate = round(close_price + self.p.trailing_stop * self.p.point, self.p.price_digits)
                threshold = close_price + (self.p.trailing_stop + self.p.trailing_step - 1) * self.p.point
                if self.stop_price is None or self.stop_price > round(threshold, self.p.price_digits):
                    self.stop_price = candidate

    def _open_long(self):
        price = float(self.data.close[0])
        self.log(f'buy stoch={float(self.stoch.percD[0]):.2f} wpr_prev={float(self.wpr[-1]):.2f}')
        self.entry_order = self.buy(size=self.p.lots)
        self.stop_price = round(price - self.p.stop_loss * self.p.point, self.p.price_digits) if self.p.stop_loss > 0 else None
        self.take_profit_price = round(price + self.p.take_profit * self.p.point, self.p.price_digits) if self.p.take_profit > 0 else None

    def _open_short(self):
        price = float(self.data.close[0])
        self.log(f'sell stoch={float(self.stoch.percD[0]):.2f} wpr_prev={float(self.wpr[-1]):.2f}')
        self.entry_order = self.sell(size=self.p.lots)
        self.stop_price = round(price + self.p.stop_loss * self.p.point, self.p.price_digits) if self.p.stop_loss > 0 else None
        self.take_profit_price = round(price - self.p.take_profit * self.p.point, self.p.price_digits) if self.p.take_profit > 0 else None

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.stochastic_period, self.p.wpr_period) + 5
        if len(self.data) < warmup:
            return

        buy_signal = self._buy_signal()
        sell_signal = self._sell_signal()
        close_price = round(float(self.data.close[0]), self.p.price_digits)
        high_price = round(float(self.data.high[0]), self.p.price_digits)
        low_price = round(float(self.data.low[0]), self.p.price_digits)

        if self.position:
            self._update_risk_prices(close_price)
            if self.position.size > 0:
                if sell_signal:
                    self.log('close long by opposite signal')
                    self.close()
                    return
                if self.stop_price is not None and low_price <= self.stop_price:
                    self.log(f'close long by stop={self.stop_price:.2f}')
                    self.close()
                    return
                if self.take_profit_price is not None and high_price >= self.take_profit_price:
                    self.log(f'close long by take_profit={self.take_profit_price:.2f}')
                    self.close()
                    return
            else:
                if buy_signal:
                    self.log('close short by opposite signal')
                    self.close()
                    return
                if self.stop_price is not None and high_price >= self.stop_price:
                    self.log(f'close short by stop={self.stop_price:.2f}')
                    self.close()
                    return
                if self.take_profit_price is not None and low_price <= self.take_profit_price:
                    self.log(f'close short by take_profit={self.take_profit_price:.2f}')
                    self.close()
                    return
            return

        if self.entry_order is not None:
            return

        if buy_signal:
            self._open_long()
            return
        if sell_signal:
            self._open_short()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                self.entry_price = round(float(order.executed.price), self.p.price_digits)
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.log(f'entry filled price={self.entry_price:.2f} size={order.executed.size:.2f}')
            else:
                self.log(f'position closed price={order.executed.price:.2f} size={order.executed.size:.2f}')
                self.stop_price = None
                self.take_profit_price = None
                self.entry_price = None
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
