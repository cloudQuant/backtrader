from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


BULL = 111111
BEAR = 222222


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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
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


class SimpleFXStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        stop_loss=30,
        take_profit=50,
        short_ma_period=50,
        short_ma_method='EMA',
        short_ma_applied_price='median',
        long_ma_period=200,
        long_ma_method='EMA',
        long_ma_applied_price='median',
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self.last_trend_direction = 0
        self.stop_price = None
        self.take_profit_price = None
        self.exit_reason = None

        short_price = self._price_line(self.p.short_ma_applied_price)
        long_price = self._price_line(self.p.long_ma_applied_price)
        self.short_ma = self._make_ma(short_price, self.p.short_ma_period, self.p.short_ma_method)
        self.long_ma = self._make_ma(long_price, self.p.long_ma_period, self.p.long_ma_method)

        self.addminperiod(max(int(self.p.short_ma_period), int(self.p.long_ma_period)) + 2)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _price_line(self, applied_price):
        name = str(applied_price).strip().lower()
        if name == 'open':
            return self.data.open
        if name == 'high':
            return self.data.high
        if name == 'low':
            return self.data.low
        if name == 'median':
            return (self.data.high + self.data.low) / 2.0
        if name == 'typical':
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if name == 'weighted':
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        return self.data.close

    def _make_ma(self, price_line, period, method):
        method_name = str(method).strip().upper()
        if method_name == 'SMA':
            return bt.indicators.SimpleMovingAverage(price_line, period=int(period))
        if method_name == 'SMMA':
            return bt.indicators.SmoothedMovingAverage(price_line, period=int(period))
        if method_name == 'LWMA' or method_name == 'WMA':
            return bt.indicators.WeightedMovingAverage(price_line, period=int(period))
        return bt.indicators.ExponentialMovingAverage(price_line, period=int(period))

    def _trend_detection(self):
        short_0 = float(self.short_ma[0])
        short_1 = float(self.short_ma[-1])
        long_0 = float(self.long_ma[0])
        long_1 = float(self.long_ma[-1])
        if short_0 > long_0 and short_1 > long_1:
            return BULL
        if short_0 < long_0 and short_1 < long_1:
            return BEAR
        return 0

    def _distance(self, points):
        return float(points) * float(self.p.point)

    def _reset_exit_levels(self):
        self.stop_price = None
        self.take_profit_price = None
        self.exit_reason = None

    def _set_exit_levels(self, side, entry_price):
        stop_dist = self._distance(self.p.stop_loss)
        take_dist = self._distance(self.p.take_profit)
        self.stop_price = None if float(self.p.stop_loss) <= 0 else round(
            entry_price - stop_dist if side == 'buy' else entry_price + stop_dist,
            int(self.p.price_digits),
        )
        self.take_profit_price = None if float(self.p.take_profit) <= 0 else round(
            entry_price + take_dist if side == 'buy' else entry_price - take_dist,
            int(self.p.price_digits),
        )

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            stop_hit = self.stop_price is not None and low <= self.stop_price
            take_hit = self.take_profit_price is not None and high >= self.take_profit_price
        else:
            stop_hit = self.stop_price is not None and high >= self.stop_price
            take_hit = self.take_profit_price is not None and low <= self.take_profit_price
        if not stop_hit and not take_hit:
            return False
        self.exit_reason = 'take_profit' if take_hit and not stop_hit else 'stop_loss'
        self.log(f'close by {self.exit_reason}')
        self.order = self.close()
        return True

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(int(self.p.short_ma_period), int(self.p.long_ma_period)) + 1:
            return
        if self.order is not None:
            return
        if self._check_exit_levels():
            return

        trend = self._trend_detection()
        if self.last_trend_direction == 0:
            if trend in (BULL, BEAR):
                self.last_trend_direction = trend
            return
        if trend == 0:
            return

        if self.position:
            if self.position.size > 0 and trend == BEAR:
                self.exit_reason = 'trend_reverse_to_bear'
                self.log('close buy on bearish trend')
                self.order = self.close()
                return
            if self.position.size < 0 and trend == BULL:
                self.exit_reason = 'trend_reverse_to_bull'
                self.log('close sell on bullish trend')
                self.order = self.close()
                return
            return

        size = float(self.p.lots)
        if trend == BULL and self.last_trend_direction == BEAR:
            self.signal_count += 1
            self.last_trend_direction = BULL
            self.log(f'open buy size={size:.2f}')
            self.order = self.buy(size=size)
            return
        if trend == BEAR and self.last_trend_direction == BULL:
            self.signal_count += 1
            self.last_trend_direction = BEAR
            self.log(f'open sell size={size:.2f}')
            self.order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                side = 'buy' if self.position.size > 0 else 'sell'
                self._set_exit_levels(side, float(order.executed.price))
                if side == 'buy':
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.log(
                    f'{side} filled price={float(order.executed.price):.2f} size={abs(float(order.executed.size)):.2f} '
                    f'sl={self.stop_price} tp={self.take_profit_price}'
                )
            else:
                self.log(f'position closed price={float(order.executed.price):.2f} reason={self.exit_reason}')
                self._reset_exit_levels()
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.log(f'order failed status={order.getstatusname()}')
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
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
