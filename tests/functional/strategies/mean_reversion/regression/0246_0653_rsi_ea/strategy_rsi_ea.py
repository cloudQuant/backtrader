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


class RsiEaStrategy(bt.Strategy):
    params = dict(
        open_buy=True,
        open_sell=True,
        close_by_signal=True,
        stop_loss=0,
        take_profit=0,
        trailing_stop=0,
        rsi_period=14,
        rsi_buy_level=30.0,
        rsi_sell_level=70.0,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

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
        self.trailing_active = False

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _set_risk(self, side, price):
        sl = float(self.p.stop_loss)
        tp = float(self.p.take_profit)
        if side == 'buy':
            self.stop_price = self._round(price - sl * self._point()) if sl > 0 else None
            self.take_profit_price = self._round(price + tp * self._point()) if tp > 0 else None
        else:
            self.stop_price = self._round(price + sl * self._point()) if sl > 0 else None
            self.take_profit_price = self._round(price - tp * self._point()) if tp > 0 else None

    def _trailing(self):
        if float(self.p.trailing_stop) <= 0 or not self.position:
            return
        ts = float(self.p.trailing_stop) * self._point()
        price = float(self.data.close[0])
        if self.position.size > 0:
            if price > float(self.position.price):
                new_sl = self._round(price - ts)
                if self.stop_price is None or new_sl > float(self.stop_price):
                    if price - 2 * ts > (float(self.stop_price) if self.stop_price else 0):
                        self.stop_price = new_sl
        else:
            if price < float(self.position.price):
                new_sl = self._round(price + ts)
                if self.stop_price is None or new_sl < float(self.stop_price):
                    if price + 2 * ts < (float(self.stop_price) if self.stop_price else float('inf')):
                        self.stop_price = new_sl

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

    def next(self):
        self.bar_num += 1
        if len(self) < self.p.rsi_period + 2:
            return
        if self.order is not None:
            return

        rsi_0 = float(self.rsi[0])
        rsi_1 = float(self.rsi[-1])

        if self.position:
            self._trailing()
            if self.p.close_by_signal:
                if self.position.size > 0 and rsi_0 < float(self.p.rsi_sell_level) and rsi_1 > float(self.p.rsi_sell_level):
                    self.order = self.close()
                    return
                if self.position.size < 0 and rsi_0 > float(self.p.rsi_buy_level) and rsi_1 < float(self.p.rsi_buy_level):
                    self.order = self.close()
                    return
            self._manage_position()
            return

        price = float(self.data.close[0])
        if self.p.open_sell and rsi_0 < float(self.p.rsi_sell_level) and rsi_1 > float(self.p.rsi_sell_level):
            self.signal_count += 1
            self._set_risk('sell', price)
            self.order = self.sell(size=self.p.lots)
            return
        if self.p.open_buy and rsi_0 > float(self.p.rsi_buy_level) and rsi_1 < float(self.p.rsi_buy_level):
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
