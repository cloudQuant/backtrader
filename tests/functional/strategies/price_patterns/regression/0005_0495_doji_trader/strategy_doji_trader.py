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


class DojiTraderStrategy(bt.Strategy):
    params = dict(
        lot=0.1,
        stop_loss_pips=50,
        take_profit_pips=50,
        start_hour=8,
        end_hour=17,
        maximum_doji_height=1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_side = 0
        self._desired_direction = 0
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def _pip_size(self):
        digits_adjust = 10 if self.p.price_digits in (3, 5) else 1
        return self.p.point * digits_adjust

    def _clear_position_state(self):
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        if not self.position:
            self._position_side = 0
            self._desired_direction = 0

    def _set_initial_protection(self):
        if not self.position:
            self._clear_position_state()
            return
        if self._entry_price is not None and self._last_position_size == self.position.size:
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        stop_distance = self.p.stop_loss_pips * pip_size
        take_distance = self.p.take_profit_pips * pip_size
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if self.p.stop_loss_pips > 0 else None
            self._take_profit_price = self._entry_price + take_distance if self.p.take_profit_pips > 0 else None
        else:
            self._stop_price = self._entry_price + stop_distance if self.p.stop_loss_pips > 0 else None
            self._take_profit_price = self._entry_price - take_distance if self.p.take_profit_pips > 0 else None

    def _current_direction(self):
        if self.position.size > 0:
            return 1
        if self.position.size < 0:
            return -1
        return 0

    def _session_open(self):
        dt = bt.num2date(self.data.datetime[0])
        return self.p.start_hour <= dt.hour < self.p.end_hour

    def _detect_signal(self):
        doji_shift = None
        doji_high = None
        doji_low = None
        max_height = self.p.maximum_doji_height * self._pip_size()
        for shift in (1, 2, 3):
            if abs(float(self.data.open[-shift]) - float(self.data.close[-shift])) <= max_height:
                doji_shift = shift
                doji_high = float(self.data.high[-shift])
                doji_low = float(self.data.low[-shift])
                break
        if doji_shift not in (2, 3):
            return 0
        last_close = float(self.data.close[-1])
        if last_close > doji_high:
            return 1
        if last_close < doji_low:
            return -1
        return 0

    def _maybe_hit_exit(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < 5:
            return
        if self.order:
            return
        if not self._session_open():
            return

        self._set_initial_protection()

        if self._maybe_hit_exit():
            return

        direction = self._detect_signal()
        if direction == 0:
            return

        current_side = self._current_direction()
        if current_side == direction:
            return

        self._desired_direction = direction
        self.order = self.order_target_size(target=direction * self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            new_side = self._current_direction()
            if new_side == 1 and self._position_side != 1:
                self.buy_count += 1
            elif new_side == -1 and self._position_side != -1:
                self.sell_count += 1
            self._position_side = new_side
            if self.position:
                self._set_initial_protection()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None
        if not self.position:
            self._clear_position_state()

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self._clear_position_state()
