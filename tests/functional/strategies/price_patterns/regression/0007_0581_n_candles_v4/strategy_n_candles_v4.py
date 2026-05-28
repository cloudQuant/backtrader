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


class NCandlesV4Strategy(bt.Strategy):
    params = dict(
        n_candles=3,
        lot=0.01,
        take_profit=50,
        stop_loss=50,
        trailing_stop=10,
        trailing_step=4,
        max_positions=2,
        max_position_volume=2.0,
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
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.pending_direction = None
        self.stop_price = None
        self.take_profit_price = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _arm(self, direction, price):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if direction == 'buy':
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None

    def _trail(self):
        if not self.position or self.order is not None or float(self.p.trailing_stop) <= 0:
            return
        ts = float(self.p.trailing_stop) * self._point()
        step = float(self.p.trailing_step) * self._point()
        current = float(self.data.close[0])
        if self.position.size > 0:
            new_sl = self._round(current - ts)
            if self.stop_price is None or new_sl > float(self.stop_price) + step:
                self.stop_price = new_sl
        else:
            new_sl = self._round(current + ts)
            if self.stop_price is None or new_sl < float(self.stop_price) - step:
                self.stop_price = new_sl

    def _check_exit(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def _same_direction_signal(self):
        if len(self) < int(self.p.n_candles) + 1:
            return None
        candle_type = 0
        for i in range(1, int(self.p.n_candles) + 1):
            o = float(self.data.open[-i])
            c = float(self.data.close[-i])
            if i == 1:
                if o < c:
                    candle_type = 1
                elif o > c:
                    candle_type = -1
                else:
                    return None
                continue
            if candle_type == 1 and o > c:
                return None
            if candle_type == -1 and o < c:
                return None
        return 'buy' if candle_type == 1 else 'sell'

    def _can_add(self, direction):
        current_volume = abs(float(self.position.size))
        if current_volume + float(self.p.lot) > float(self.p.max_position_volume):
            return False
        return True

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        if not self.position and self.pending_direction is not None:
            price = float(self.data.close[0])
            self._arm(self.pending_direction, price)
            self.signal_count += 1
            self.order = self.buy(size=self.p.lot) if self.pending_direction == 'buy' else self.sell(size=self.p.lot)
            self.pending_direction = None
            return

        if self.position:
            self._trail()
            self._check_exit()
            if self.order is not None:
                return

        signal = self._same_direction_signal()
        if signal is None:
            return

        if signal == 'buy':
            if self.position.size < 0:
                self.pending_direction = 'buy'
                self.order = self.close()
                return
            if self._can_add('buy'):
                price = float(self.data.close[0])
                self._arm('buy', price)
                self.signal_count += 1
                self.order = self.buy(size=self.p.lot)
        else:
            if self.position.size > 0:
                self.pending_direction = 'sell'
                self.order = self.close()
                return
            if self._can_add('sell'):
                price = float(self.data.close[0])
                self._arm('sell', price)
                self.signal_count += 1
                self.order = self.sell(size=self.p.lot)

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
