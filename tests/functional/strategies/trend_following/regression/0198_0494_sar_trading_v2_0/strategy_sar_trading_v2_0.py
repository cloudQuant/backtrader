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


class SarTradingV20Strategy(bt.Strategy):
    params = dict(
        lot=0.1,
        stop_loss_pips=50,
        take_profit_pips=50,
        trailing_stop_pips=15,
        trailing_step_pips=5,
        ma_period=18,
        ma_shift=2,
        ma_method='sma',
        sar_step=0.02,
        sar_maximum=0.2,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        ma_cls = bt.indicators.SimpleMovingAverage if str(self.p.ma_method).lower() == 'sma' else bt.indicators.ExponentialMovingAverage
        self.ma = ma_cls(self.data.close, period=self.p.ma_period)
        self.sar = bt.indicators.ParabolicSAR(self.data, af=self.p.sar_step, afmax=self.p.sar_maximum)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_side = 0
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

    def _shifted_ma_value(self):
        shift = max(0, int(self.p.ma_shift))
        return float(self.ma[-shift]) if shift else float(self.ma[0])

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

    def _update_trailing(self):
        if not self.position or self.p.trailing_stop_pips <= 0:
            return
        current_price = float(self.data.close[0])
        pip_size = self._pip_size()
        trail_stop = self.p.trailing_stop_pips * pip_size
        trail_step = self.p.trailing_step_pips * pip_size
        if self.position.size > 0:
            if current_price - self._entry_price > trail_stop + trail_step:
                threshold = current_price - (trail_stop + trail_step)
                candidate = current_price - trail_stop
                if self._stop_price is None or self._stop_price < threshold:
                    self._stop_price = candidate
        else:
            if self._entry_price - current_price > trail_stop + trail_step:
                threshold = current_price + (trail_stop + trail_step)
                candidate = current_price + trail_stop
                if self._stop_price is None or self._stop_price > threshold or self._stop_price == 0:
                    self._stop_price = candidate

    def next(self):
        self.bar_num += 1
        warmup = self.p.ma_period + max(2, self.p.ma_shift) + 5
        if len(self.data) < warmup:
            return
        if self.order:
            return

        if self.position:
            self._set_initial_protection()
            if self._maybe_hit_exit():
                return
            self._update_trailing()
            return

        sar_val = float(self.sar[0])
        ma_val = self._shifted_ma_value()
        close_shifted = float(self.data.close[-max(1, self.p.ma_shift)])

        buy_signal = sar_val < ma_val or close_shifted < ma_val
        sell_signal = sar_val > ma_val or close_shifted > ma_val

        if buy_signal:
            self.buy_count += 1
            self.order = self.buy(size=self.p.lot)
            return
        if sell_signal:
            self.sell_count += 1
            self.order = self.sell(size=self.p.lot)
            return

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            self._position_side = 1 if self.position.size > 0 else -1 if self.position.size < 0 else 0
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
