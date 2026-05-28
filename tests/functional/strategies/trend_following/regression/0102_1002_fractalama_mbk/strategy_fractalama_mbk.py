from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader.feeds as btfeeds
import backtrader.indicators as btind
from backtrader.indicator import Indicator
from backtrader.strategy import Strategy
from backtrader.utils.dateintern import num2date
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class FractalAMAMBK(Indicator):
    lines = ('frama', 'trigger')
    params = dict(
        r_period=16,
        multiplier=4.6,
        signal_multiplier=2.5,
    )

    def __init__(self):
        self.addminperiod(max(int(self.p.r_period), 2) + 2)

    def _range(self, high_line, low_line, start_shift, count):
        highs = [float(high_line[-shift]) if shift else float(high_line[0]) for shift in range(start_shift, start_shift + count)]
        lows = [float(low_line[-shift]) if shift else float(low_line[0]) for shift in range(start_shift, start_shift + count)]
        return max(highs) - min(lows)

    def next(self):
        period = max(int(self.p.r_period), 2)
        n = (period // 2) * 2
        n2 = max(n // 2, 1)
        price = float(self.data.close[0])

        if len(self.data) <= n:
            self.l.frama[0] = price
            self.l.trigger[0] = price
            return

        r1 = self._range(self.data.high, self.data.low, 0, n2) / n2
        r2 = self._range(self.data.high, self.data.low, n2, n2) / n2
        r3 = self._range(self.data.high, self.data.low, 0, n) / n

        if r3 <= 0 or (r1 + r2) <= 0:
            dimension_estimate = 1.0
        else:
            dimension_estimate = (math.log(r1 + r2) - math.log(r3)) * 1.442695

        alpha = math.exp(-float(self.p.multiplier) * (dimension_estimate - 1.0))
        alpha = min(max(alpha, 0.01), 1.0)
        alphas = math.exp(-float(self.p.signal_multiplier) * (dimension_estimate - 1.0))

        prev_frama = float(self.l.frama[-1]) if len(self.data) > 1 and math.isfinite(float(self.l.frama[-1])) else float(self.data.close[-1])
        prev_trigger = float(self.l.trigger[-1]) if len(self.data) > 1 and math.isfinite(float(self.l.trigger[-1])) else prev_frama

        frama = alpha * price + (1.0 - alpha) * prev_frama
        trigger = alphas * frama + (1.0 - alphas) * prev_trigger
        self.l.frama[0] = frama
        self.l.trigger[0] = trigger


class FractalAMAMBKStrategy(Strategy):
    params = dict(
        signal_bar=1,
        r_period=16,
        multiplier=4.6,
        signal_multiplier=2.5,
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
    )

    def __init__(self):
        self.indicator = FractalAMAMBK(
            self.data,
            r_period=self.p.r_period,
            multiplier=self.p.multiplier,
            signal_multiplier=self.p.signal_multiplier,
        )
        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.pending_entry_direction = 0
        self.warmup = max(int(self.p.r_period) + max(int(self.p.signal_bar), 1) + 5, 30)

    def log(self, text):
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signal_shifts(self):
        current = max(int(self.p.signal_bar), 1)
        previous = current + 1
        return current, previous

    def _get_signals(self):
        current, previous = self._signal_shifts()
        ind_curr = float(self.indicator.frama[-current])
        sig_curr = float(self.indicator.trigger[-current])
        ind_prev = float(self.indicator.frama[-previous])
        sig_prev = float(self.indicator.trigger[-previous])
        buy_open = self.p.buy_pos_open and ind_prev > sig_prev and ind_curr <= sig_curr
        sell_open = self.p.sell_pos_open and ind_prev < sig_prev and ind_curr >= sig_curr
        buy_close = self.p.buy_pos_close and sell_open
        sell_close = self.p.sell_pos_close and buy_open
        return buy_open, sell_open, buy_close, sell_close

    def _reset_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None

    def _open_long(self):
        self.pending_entry_direction = 1
        self.buy(size=self.p.lot)

    def _open_short(self):
        self.pending_entry_direction = -1
        self.sell(size=self.p.lot)

    def _close_long(self, reason):
        self.log(reason)
        self.close()
        self._reset_levels()

    def _close_short(self, reason):
        self.log(reason)
        self.close()
        self._reset_levels()

    def _manage_protective_levels(self):
        if not self.position or self.entry_price is None:
            return False
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self._close_long(f'close long stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and high >= self.target_price:
                self._close_long(f'close long target={self.target_price:.2f}')
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self._close_short(f'close short stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and low <= self.target_price:
                self._close_short(f'close short target={self.target_price:.2f}')
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.warmup + max(int(self.p.signal_bar), 1) + 1:
            return
        if self._manage_protective_levels():
            return

        buy_open, sell_open, buy_close, sell_close = self._get_signals()

        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1

        if self.position:
            if self.position.size > 0:
                if buy_close:
                    self._close_long('close long on bearish crossover')
                    if sell_open:
                        self._open_short()
                    return
            else:
                if sell_close:
                    self._close_short('close short on bullish crossover')
                    if buy_open:
                        self._open_long()
                    return
        else:
            if buy_open:
                self.log('buy on frama crossover')
                self._open_long()
                return
            if sell_open:
                self.log('sell on frama crossover')
                self._open_short()
                return

    def notify_order(self, order):
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.pending_entry_direction = 0
            self.log(f'order {order.getstatusname()}')
            return
        if order.status != order.Completed:
            return
        self.completed_order_count += 1
        if self.pending_entry_direction == 1 and order.isbuy():
            self.buy_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return
        if self.pending_entry_direction == -1 and order.issell():
            self.sell_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return
        if not self.position:
            self._reset_levels()

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
