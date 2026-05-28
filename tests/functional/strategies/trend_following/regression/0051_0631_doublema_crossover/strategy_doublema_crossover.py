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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


class DoubleMACrossoverStrategy(bt.Strategy):
    """EA 0631: Dual MA crossover with breakout level, trailing stop, and time filter.
    Buy when fast MA - slow MA > breakout_level (at signal candle).
    Sell when slow MA - fast MA > breakout_level.
    Exit on reverse crossover. Trailing stop with 3-level support.
    """

    params = dict(
        fast_ma_period=2,
        slow_ma_period=5,
        breakout_level=45,
        signal_candle=1,
        stop_loss=25,
        take_profit=0,
        use_trailing_stop=False,
        trailing_stop=40,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_ma_period)
        self.ma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_ma_period)

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

    def _set_risk(self, side, price):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if side == 'buy':
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None

    def _trailing(self):
        if not self.position or self.order is not None or not self.p.use_trailing_stop:
            return
        ts = float(self.p.trailing_stop) * self._point()
        price = float(self.data.close[0])
        if self.position.size > 0:
            new_sl = self._round(price - ts)
            if self.stop_price is None or new_sl > float(self.stop_price):
                self.stop_price = new_sl
        elif self.position.size < 0:
            new_sl = self._round(price + ts)
            if self.stop_price is None or new_sl < float(self.stop_price):
                self.stop_price = new_sl

    def _check_exit(self):
        if not self.position or self.order is not None:
            return
        sc = int(self.p.signal_candle)
        fma = float(self.ma_fast[-sc])
        sma = float(self.ma_slow[-sc])
        high = float(self.data.high[0])
        low = float(self.data.low[0])

        if self.position.size > 0:
            if fma - sma < 0:
                self.order = self.close(); return
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
        else:
            if fma - sma > 0:
                self.order = self.close(); return
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self) < max(self.p.fast_ma_period, self.p.slow_ma_period) + 2:
            return
        if self.order is not None:
            return
        if self.position:
            self._trailing()
            self._check_exit()
            return

        sc = int(self.p.signal_candle)
        fma = float(self.ma_fast[-sc])
        sma = float(self.ma_slow[-sc])
        breakout = float(self.p.breakout_level) * self._point()
        price = float(self.data.close[0])

        if fma - sma > breakout:
            self.signal_count += 1
            self._set_risk('buy', price)
            self.order = self.buy(size=self.p.lots)
        elif sma - fma > breakout:
            self.signal_count += 1
            self._set_risk('sell', price)
            self.order = self.sell(size=self.p.lots)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0: self.buy_count += 1
                elif order.executed.size < 0: self.sell_count += 1
            else:
                self.stop_price = None; self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0: self.win_count += 1
        else: self.loss_count += 1
