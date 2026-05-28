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


class MomoTradesStrategy(bt.Strategy):
    params = dict(
        manual_lot=True,
        lot=0.1,
        stop_loss_pips=25,
        take_profit_pips=0,
        trailing_stop_pips=0,
        trailing_step_pips=5,
        breakeven_pips=10,
        risk_percent=10.0,
        price_shift_pips=5,
        close_end_day=True,
        ma_period=22,
        ma_bar=6,
        fast_ema_period=12,
        slow_ema_period=26,
        signal_period=9,
        macd_bar=2,
        point=0.01,
        price_digits=2,
        contract_multiplier=100.0,
        min_lot=0.01,
    )

    def __init__(self):
        self.ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.ma_period)
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.fast_ema_period,
            period_me2=self.p.slow_ema_period,
            period_signal=self.p.signal_period,
        )
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def _pip_size(self):
        digits_adjust = 10 if self.p.price_digits in (3, 5) else 1
        return self.p.point * digits_adjust

    def _risk_based_size(self, entry_price, stop_price):
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return self.p.lot
        risk_cash = self.broker.getcash() * (self.p.risk_percent / 100.0)
        raw_size = risk_cash / (stop_distance * self.p.contract_multiplier)
        size = max(self.p.min_lot, raw_size)
        return round(size, 2)

    def _entry_size(self, direction):
        if self.p.manual_lot or self.p.stop_loss_pips <= 0:
            return self.p.lot
        pip_size = self._pip_size()
        stop_distance = self.p.stop_loss_pips * pip_size
        entry_price = float(self.data.close[0])
        stop_price = entry_price - stop_distance if direction > 0 else entry_price + stop_distance
        return self._risk_based_size(entry_price, stop_price)

    def _clear_position_state(self):
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        self._position_was_open = False

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

    def _macd_values(self):
        return [float(self.macd.macd[-(self.p.macd_bar + i)]) for i in range(11)]

    def _macd_buy(self):
        values = self._macd_values()
        return (
            values[3] > values[4]
            and values[4] > values[5]
            and values[5] >= 0.0
            and values[6] <= 0.0
            and values[6] > values[7]
            and values[7] > values[8]
        )

    def _macd_sell(self):
        values = self._macd_values()
        return (
            values[3] < values[4]
            and values[4] < values[5]
            and values[5] <= 0.0
            and values[6] >= 0.0
            and values[6] < values[7]
            and values[7] < values[8]
        )

    def _ema_buy(self):
        close_val = float(self.data.close[-self.p.ma_bar])
        ma_val = float(self.ma[-self.p.ma_bar])
        return close_val - ma_val > self.p.price_shift_pips * self._pip_size()

    def _ema_sell(self):
        close_val = float(self.data.close[-self.p.ma_bar])
        ma_val = float(self.ma[-self.p.ma_bar])
        return ma_val - close_val > self.p.price_shift_pips * self._pip_size()

    def _maybe_close_end_day(self):
        if not self.p.close_end_day:
            return False
        dt = bt.num2date(self.data.datetime[0])
        end_hour = 21 if dt.weekday() == 4 else 23
        if dt.hour >= end_hour:
            if self.position:
                self.order = self.close()
            return True
        return False

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
        if not self.position:
            return
        current_price = float(self.data.close[0])
        pip_size = self._pip_size()
        trail_stop = self.p.trailing_stop_pips * pip_size
        trail_step = self.p.trailing_step_pips * pip_size
        breakeven = self.p.breakeven_pips * pip_size
        if self.position.size > 0:
            if self.p.take_profit_pips > 0 and self.p.trailing_stop_pips > 0:
                if current_price - self._entry_price > trail_stop + trail_step:
                    candidate = current_price - trail_stop
                    threshold = current_price - (trail_stop + trail_step)
                    if self._stop_price is None or self._stop_price < threshold:
                        self._stop_price = candidate
            elif self.p.take_profit_pips == 0 and self.p.breakeven_pips > 0:
                if self._stop_price != self._entry_price and self._entry_price + breakeven < current_price:
                    self._stop_price = self._entry_price
        else:
            if self.p.take_profit_pips > 0 and self.p.trailing_stop_pips > 0:
                if self._entry_price - current_price > trail_stop + trail_step:
                    candidate = current_price + trail_stop
                    threshold = current_price + (trail_stop + trail_step)
                    if self._stop_price is None or self._stop_price > threshold or self._stop_price == 0:
                        self._stop_price = candidate
            elif self.p.take_profit_pips == 0 and self.p.breakeven_pips > 0:
                if self._stop_price != self._entry_price and self._entry_price - breakeven > current_price:
                    self._stop_price = self._entry_price

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.ma_period + self.p.ma_bar + 2, self.p.slow_ema_period + self.p.signal_period + self.p.macd_bar + 12)
        if len(self.data) < warmup:
            return
        if self.order:
            return

        self._set_initial_protection()

        if self._maybe_close_end_day():
            return

        if self._maybe_hit_exit():
            return

        self._update_trailing()

        if self.position:
            return

        if self._macd_buy() and self._ema_buy():
            self.order = self.buy(size=self._entry_size(1))
            return

        if self._macd_sell() and self._ema_sell():
            self.order = self.sell(size=self._entry_size(-1))
            return

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed and self.position:
            self._set_initial_protection()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None
        if not self.position:
            self._clear_position_state()

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._clear_position_state()
