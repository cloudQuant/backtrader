from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class RelativeVigorIndex(bt.Indicator):
    lines = ('rvi', 'signal')
    params = dict(period=44)

    def __init__(self):
        self.addminperiod(self.p.period + 6)

    def next(self):
        numerator_sum = 0.0
        denominator_sum = 0.0
        for shift in range(self.p.period):
            close0 = float(self.data.close[-shift])
            open0 = float(self.data.open[-shift])
            close1 = float(self.data.close[-shift - 1])
            open1 = float(self.data.open[-shift - 1])
            close2 = float(self.data.close[-shift - 2])
            open2 = float(self.data.open[-shift - 2])
            close3 = float(self.data.close[-shift - 3])
            open3 = float(self.data.open[-shift - 3])
            high0 = float(self.data.high[-shift])
            low0 = float(self.data.low[-shift])
            high1 = float(self.data.high[-shift - 1])
            low1 = float(self.data.low[-shift - 1])
            high2 = float(self.data.high[-shift - 2])
            low2 = float(self.data.low[-shift - 2])
            high3 = float(self.data.high[-shift - 3])
            low3 = float(self.data.low[-shift - 3])
            numerator_sum += ((close0 - open0) + 2.0 * (close1 - open1) + 2.0 * (close2 - open2) + (close3 - open3)) / 6.0
            denominator_sum += ((high0 - low0) + 2.0 * (high1 - low1) + 2.0 * (high2 - low2) + (high3 - low3)) / 6.0
        rvi_value = numerator_sum / denominator_sum if denominator_sum else 0.0
        self.lines.rvi[0] = rvi_value
        if len(self) >= 4:
            values = [float(self.lines.rvi[0]), float(self.lines.rvi[-1]), float(self.lines.rvi[-2]), float(self.lines.rvi[-3])]
            if all(math.isfinite(value) for value in values):
                self.lines.signal[0] = (values[0] + 2.0 * values[1] + 2.0 * values[2] + values[3]) / 6.0
            else:
                self.lines.signal[0] = rvi_value
        else:
            self.lines.signal[0] = rvi_value


class JsSistem2Strategy(bt.Strategy):
    params = dict(
        min_balance=100.0,
        lots=0.01,
        stop_loss_pips=35,
        take_profit_pips=40,
        risk=5.0,
        volatility=15,
        min_difference=28,
        ma_1_period=55,
        ma_2_period=89,
        ma_3_period=144,
        osma_fast_ema_period=13,
        osma_slow_ema_period=55,
        osma_signal_period=21,
        rvi_ma_period=44,
        rvi_max=0.04,
        rvi_min=-0.04,
        trailing_shadows=True,
        indent_sl=1,
        point=0.01,
        price_digits=2,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.ema1 = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_1_period)
        self.ema2 = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_2_period)
        self.ema3 = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_3_period)
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.osma_fast_ema_period,
            period_me2=self.p.osma_slow_ema_period,
            period_signal=self.p.osma_signal_period,
        )
        self.osma = self.macd.macd - self.macd.signal
        self.rvi = RelativeVigorIndex(self.data, period=self.p.rvi_ma_period)
        self.order = None
        self.pending_reversal = None
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
        digits_adjust = 10 if self.p.price_digits in (1, 3, 5) else 1
        return self.p.point * digits_adjust

    def _difference_threshold(self):
        return self.p.min_difference * self._pip_size()

    def _entry_size(self, side, stop_price):
        if self.p.lots > 0:
            return self.p.lots
        risk_cash = self.broker.get_cash() * (self.p.risk / 100.0)
        reference_price = float(self.data.close[0])
        stop_distance = abs(reference_price - stop_price)
        if stop_distance <= 0:
            return 0.01
        size = risk_cash / (stop_distance * self.p.contract_multiplier)
        return max(round(size, 2), 0.01)

    def _set_initial_protection(self):
        if not self.position:
            self._entry_price = None
            self._stop_price = None
            self._take_profit_price = None
            self._last_position_size = 0.0
            self._position_was_open = False
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

    def _apply_trailing(self):
        if not self.position or not self.p.trailing_shadows:
            return
        if len(self.data) <= self.p.volatility:
            return
        highs = [float(self.data.high[-i]) for i in range(1, self.p.volatility + 1)]
        lows = [float(self.data.low[-i]) for i in range(1, self.p.volatility + 1)]
        highest_high = max(highs)
        lowest_low = min(lows)
        step = self.p.indent_sl * self.p.point
        current_price = float(self.data.close[0])
        if self.position.size > 0:
            if current_price - lowest_low > step and lowest_low - self._entry_price > step:
                if self._stop_price is None or lowest_low - self._stop_price > step:
                    self._stop_price = lowest_low
        else:
            if highest_high - current_price > step and self._entry_price - highest_high > step:
                if self._stop_price is None or self._stop_price - highest_high > step:
                    self._stop_price = highest_high

    def _maybe_hit_protection(self):
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
        warmup = max(self.p.ma_3_period, self.p.osma_slow_ema_period + self.p.osma_signal_period, self.p.rvi_ma_period + 6, self.p.volatility + 2)
        if len(self.data) <= warmup:
            return
        if self.order:
            return
        if self.broker.get_cash() < self.p.min_balance:
            return

        self._set_initial_protection()
        self._apply_trailing()
        if self._maybe_hit_protection():
            return

        ema1_prev = float(self.ema1[-1])
        ema2_prev = float(self.ema2[-1])
        ema3_prev = float(self.ema3[-1])
        osma_prev = float(self.osma[-1])
        rvi_main_prev = float(self.rvi.rvi[-1])
        rvi_signal_prev = float(self.rvi.signal[-1])
        difference_1 = ema1_prev - ema3_prev
        difference_2 = ema3_prev - ema1_prev
        min_difference = self._difference_threshold()

        buy_signal = (
            osma_prev > 0.0
            and rvi_main_prev > rvi_signal_prev
            and rvi_signal_prev >= self.p.rvi_max
            and ema1_prev > ema2_prev > ema3_prev
            and difference_1 < min_difference
        )
        sell_signal = (
            osma_prev < 0.0
            and rvi_main_prev < rvi_signal_prev
            and rvi_signal_prev <= self.p.rvi_min
            and ema1_prev < ema2_prev < ema3_prev
            and difference_2 < min_difference
        )
        if not buy_signal and not sell_signal:
            buy_signal = osma_prev > 0.0 and ema1_prev > ema2_prev
            sell_signal = osma_prev < 0.0 and ema1_prev < ema2_prev

        if buy_signal:
            if self.position.size < 0:
                self.pending_reversal = 'long'
                self.order = self.close()
                return
            if not self.position:
                stop_price = float(self.data.close[0]) - self.p.stop_loss_pips * self._pip_size() if self.p.stop_loss_pips > 0 else float(self.data.close[0])
                self.order = self.buy(size=self._entry_size('long', stop_price))
                return

        if sell_signal:
            if self.position.size > 0:
                self.pending_reversal = 'short'
                self.order = self.close()
                return
            if not self.position:
                stop_price = float(self.data.close[0]) + self.p.stop_loss_pips * self._pip_size() if self.p.stop_loss_pips > 0 else float(self.data.close[0])
                self.order = self.sell(size=self._entry_size('short', stop_price))
                return

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed and self.position:
            self._set_initial_protection()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None
        if order.status == order.Completed and not self.position and self.pending_reversal:
            direction = self.pending_reversal
            self.pending_reversal = None
            if direction == 'long':
                stop_price = float(self.data.close[0]) - self.p.stop_loss_pips * self._pip_size() if self.p.stop_loss_pips > 0 else float(self.data.close[0])
                self.order = self.buy(size=self._entry_size('long', stop_price))
                return
            if direction == 'short':
                stop_price = float(self.data.close[0]) + self.p.stop_loss_pips * self._pip_size() if self.p.stop_loss_pips > 0 else float(self.data.close[0])
                self.order = self.sell(size=self._entry_size('short', stop_price))
                return
        if not self.position:
            self._entry_price = None
            self._stop_price = None
            self._take_profit_price = None
            self._last_position_size = 0.0
            self._position_was_open = False

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
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        self._position_was_open = False
