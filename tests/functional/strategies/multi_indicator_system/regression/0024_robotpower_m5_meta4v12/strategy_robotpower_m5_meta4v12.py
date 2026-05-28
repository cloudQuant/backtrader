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


class RobotPowerM5Meta4V12Strategy(bt.Strategy):
    params = dict(
        bull_bear_period=5,
        lot=0.01,
        trailing_step=10,
        take_profit=150,
        stop_loss=105,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.bull_bear_period)
        self.atr = bt.indicators.ATR(self.data, period=5)
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
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _bull(self, idx):
        return float(self.data.high[idx]) - float(self.ema[idx])

    def _bear(self, idx):
        return float(self.data.low[idx]) - float(self.ema[idx])

    def _combined(self, idx):
        return self._bull(idx) + self._bear(idx)

    def _set_risk_prices(self, is_long, price):
        self.stop_price = round(price - self.p.stop_loss * self.p.point, self.p.price_digits) if is_long else round(price + self.p.stop_loss * self.p.point, self.p.price_digits)
        self.take_profit_price = round(price + self.p.take_profit * self.p.point, self.p.price_digits) if is_long else round(price - self.p.take_profit * self.p.point, self.p.price_digits)

    def _apply_trailing(self, close_price):
        if not self.position or self.stop_price is None:
            return
        if self.position.size > 0:
            if close_price - self.stop_price > 2 * self.p.trailing_step * self.p.point:
                new_stop = round(close_price - self.p.trailing_step * self.p.point, self.p.price_digits)
                if new_stop > self.stop_price:
                    self.stop_price = new_stop
        else:
            if self.stop_price - close_price > 2 * self.p.trailing_step * self.p.point:
                new_stop = round(close_price + self.p.trailing_step * self.p.point, self.p.price_digits)
                if new_stop < self.stop_price:
                    self.stop_price = new_stop

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(200, self.p.bull_bear_period + 5):
            return
        if self.entry_order is not None:
            return

        signal = self._combined(-1)
        is_buying = signal > 0
        is_selling = signal < 0
        close_price = round(float(self.data.close[0]), self.p.price_digits)
        high_price = round(float(self.data.high[0]), self.p.price_digits)
        low_price = round(float(self.data.low[0]), self.p.price_digits)

        if self.position:
            self._apply_trailing(close_price)
            if self.position.size > 0:
                if low_price <= self.stop_price:
                    self.log(f'close long by stop={self.stop_price:.2f}')
                    self.entry_order = self.close()
                    return
                if high_price >= self.take_profit_price:
                    self.log(f'close long by take_profit={self.take_profit_price:.2f}')
                    self.entry_order = self.close()
                    return
            else:
                if high_price >= self.stop_price:
                    self.log(f'close short by stop={self.stop_price:.2f}')
                    self.entry_order = self.close()
                    return
                if low_price <= self.take_profit_price:
                    self.log(f'close short by take_profit={self.take_profit_price:.2f}')
                    self.entry_order = self.close()
                    return
            return

        if is_buying and not is_selling:
            self.log(f'buy bull+bears={signal:.4f}')
            self._set_risk_prices(True, close_price)
            self.entry_order = self.buy(size=self.p.lot)
            return
        if is_selling and not is_buying:
            self.log(f'sell bull+bears={signal:.4f}')
            self._set_risk_prices(False, close_price)
            self.entry_order = self.sell(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if order.executed.size > 0:
                self.buy_count += 1
            elif order.executed.size < 0:
                self.sell_count += 1
            if not self.position:
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
