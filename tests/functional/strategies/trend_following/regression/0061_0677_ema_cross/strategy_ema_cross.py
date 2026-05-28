from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
    })
    if '<VOL>' in df.columns:
        df['openinterest'] = df['<VOL>']
    else:
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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class EmaCrossStrategy(bt.Strategy):
    params = dict(
        reverse=True,
        take_profit=25,
        stop_loss=105,
        lots=0.5,
        trailing_stop=20,
        short_ema=9,
        long_ema=45,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ema_short = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.short_ema)
        self.ema_long = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.long_ema)
        self.order = None
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        self._last_direction = 0
        self._first_time = True

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _distance_unit(self):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _crossed(self, line1, line2):
        current_direction = 1 if line1 > line2 else 2
        if self._first_time:
            self._first_time = False
            self._last_direction = current_direction
            return 0
        if current_direction != self._last_direction:
            self._last_direction = current_direction
            return current_direction
        return 0

    def _sync_position_state(self):
        if not self.position:
            self._entry_price = None
            self._stop_price = None
            self._take_profit_price = None
            self._last_position_size = 0.0
            return
        if self._entry_price is not None and self._last_position_size == float(self.position.size):
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        distance_unit = self._distance_unit()
        stop_distance = float(self.p.stop_loss) * distance_unit
        take_distance = float(self.p.take_profit) * distance_unit
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance
            self._take_profit_price = self._entry_price + take_distance
        else:
            self._stop_price = self._entry_price + stop_distance
            self._take_profit_price = self._entry_price - take_distance

    def _update_trailing(self):
        if not self.position or float(self.p.trailing_stop) <= 0:
            return
        distance = float(self.p.trailing_stop) * self._distance_unit()
        close = float(self.data.close[0])
        if self.position.size > 0 and close - self._entry_price > distance:
            candidate = round(close - distance, self.p.price_digits)
            if self._stop_price is None or candidate > self._stop_price:
                self._stop_price = candidate
        if self.position.size < 0 and self._entry_price - close > distance:
            candidate = round(close + distance, self.p.price_digits)
            if self._stop_price is None or candidate < self._stop_price:
                self._stop_price = candidate

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.log(f'close long stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.log(f'close long tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.log(f'close short stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.log(f'close short tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.long_ema + 2:
            return
        if self.order is not None:
            return
        self._sync_position_state()
        self._update_trailing()
        if self._manage_risk():
            return
        crossed = self._crossed(float(self.ema_short[0]), float(self.ema_long[0])) if self.p.reverse else self._crossed(float(self.ema_long[0]), float(self.ema_short[0]))
        if self.position:
            return
        if crossed == 1:
            self.signal_count += 1
            self.log('buy signal on EMA cross')
            self.order = self.buy(size=float(self.p.lots))
            return
        if crossed == 2:
            self.signal_count += 1
            self.log('sell signal on EMA cross')
            self.order = self.sell(size=float(self.p.lots))

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            self._sync_position_state()
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

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
