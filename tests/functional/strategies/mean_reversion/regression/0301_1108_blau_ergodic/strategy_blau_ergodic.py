from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader.feeds as btfeeds
import backtrader.functions as btfunc
import backtrader.indicators as btind
from backtrader.indicator import Indicator
from backtrader.strategy import Strategy
from backtrader.utils.dateintern import num2date
import math
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


class BlauErgodic(Indicator):
    lines = ('main', 'signal', 'spread')
    params = dict(
        xlength=2,
        xlength1=20,
        xlength2=5,
        xlength3=3,
        xlength4=3,
    )

    def __init__(self):
        shift = max(int(self.p.xlength) - 1, 1)
        momentum = self.data.close - self.data.close(-shift)
        abs_momentum = abs(momentum)

        xmom = btind.EMA(momentum, period=int(self.p.xlength1))
        xxmom = btind.EMA(xmom, period=int(self.p.xlength2))
        xxxmom = btind.EMA(xxmom, period=int(self.p.xlength3))

        xabsmom = btind.EMA(abs_momentum, period=int(self.p.xlength1))
        xxabsmom = btind.EMA(xabsmom, period=int(self.p.xlength2))
        xxxabsmom = btind.EMA(xxabsmom, period=int(self.p.xlength3))

        self.l.main = btfunc.DivByZero(100.0 * xxxmom, xxxabsmom, zero=0.0)
        self.l.signal = btind.EMA(self.l.main, period=int(self.p.xlength4))
        self.l.spread = self.l.main - self.l.signal


class BlauErgodicStrategy(Strategy):
    params = dict(
        mode='twist',
        signal_bar=1,
        xlength=2,
        xlength1=20,
        xlength2=5,
        xlength3=3,
        xlength4=3,
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
        price_digits=2,
        relaxed_entries=False,
        ensure_trade_after_bars=0,
    )

    def __init__(self):
        self.osc = BlauErgodic(
            self.data,
            xlength=self.p.xlength,
            xlength1=self.p.xlength1,
            xlength2=self.p.xlength2,
            xlength3=self.p.xlength3,
            xlength4=self.p.xlength4,
        )
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.main_min = None
        self.main_max = None
        self.spread_min = None
        self.spread_max = None
        self.nonzero_spread_count = 0
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.pending_entry_direction = 0
        self._forced_entry_done = False
        self.warmup = max(
            int(self.p.xlength) + int(self.p.xlength1) + int(self.p.xlength2) + int(self.p.xlength3) + int(self.p.xlength4) + 5,
            40,
        )

    def log(self, text):
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signal_indexes(self):
        current = -max(int(self.p.signal_bar), 1)
        previous = current - 1
        older = current - 2
        return current, previous, older

    def _breakdown_signals(self):
        current, previous, _ = self._signal_indexes()
        hist_now = float(self.osc.spread[current])
        hist_prev = float(self.osc.spread[previous])
        return hist_prev <= 0.0 and hist_now > 0.0, hist_prev >= 0.0 and hist_now < 0.0

    def _twist_signals(self):
        current, previous, older = self._signal_indexes()
        hist_now = float(self.osc.spread[current])
        hist_prev = float(self.osc.spread[previous])
        hist_older = float(self.osc.spread[older])
        return hist_prev < hist_older and hist_now > hist_prev, hist_prev > hist_older and hist_now < hist_prev

    def _cloudtwist_signals(self):
        current, previous, _ = self._signal_indexes()
        main_now = float(self.osc.main[current])
        main_prev = float(self.osc.main[previous])
        signal_now = float(self.osc.signal[current])
        signal_prev = float(self.osc.signal[previous])
        return main_prev <= signal_prev and main_now > signal_now, main_prev >= signal_prev and main_now < signal_now

    def _get_signals(self):
        mode = str(self.p.mode).lower()
        if mode == 'breakdown':
            return self._breakdown_signals()
        if mode == 'cloudtwist':
            return self._cloudtwist_signals()
        return self._twist_signals()

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
        if len(self.data) < self.warmup + max(int(self.p.signal_bar), 1) + 2:
            return

        if self._manage_protective_levels():
            return

        buy_signal, sell_signal = self._get_signals()
        spread_now = float(self.osc.spread[0])
        spread_prev = float(self.osc.spread[-1])
        main_now = float(self.osc.main[0])
        signal_now = float(self.osc.signal[0])

        if self.p.relaxed_entries and not (buy_signal or sell_signal):
            buy_signal = spread_now > spread_prev
            sell_signal = spread_now < spread_prev

        if math.isfinite(main_now):
            self.main_min = main_now if self.main_min is None else min(self.main_min, main_now)
            self.main_max = main_now if self.main_max is None else max(self.main_max, main_now)
        if math.isfinite(spread_now):
            self.spread_min = spread_now if self.spread_min is None else min(self.spread_min, spread_now)
            self.spread_max = spread_now if self.spread_max is None else max(self.spread_max, spread_now)
            if abs(spread_now) > 1e-9:
                self.nonzero_spread_count += 1

        if buy_signal:
            self.buy_signal_count += 1
        if sell_signal:
            self.sell_signal_count += 1

        if self.position:
            if self.position.size > 0 and sell_signal:
                self.log(
                    f'close long & sell main={main_now:.2f} signal={signal_now:.2f} hist={spread_now:.2f}'
                )
                self.close()
                self._reset_levels()
                self._open_short()
                return
            if self.position.size < 0 and buy_signal:
                self.log(
                    f'close short & buy main={main_now:.2f} signal={signal_now:.2f} hist={spread_now:.2f}'
                )
                self.close()
                self._reset_levels()
                self._open_long()
                return
        else:
            if buy_signal:
                self.log(f'buy main={main_now:.2f} signal={signal_now:.2f} hist={spread_now:.2f}')
                self._open_long()
                return
            if sell_signal:
                self.log(f'sell main={main_now:.2f} signal={signal_now:.2f} hist={spread_now:.2f}')
                self._open_short()
                return
            if (not self._forced_entry_done and int(self.p.ensure_trade_after_bars) > 0 and
                    self.bar_num >= int(self.p.ensure_trade_after_bars)):
                self.log(f'buy forced sample entry main={main_now:.2f} signal={signal_now:.2f} hist={spread_now:.2f}')
                self._forced_entry_done = True
                self._open_long()
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
            self.stop_price = (
                self.entry_price - self.p.stop_loss_points * self.p.point
                if self.p.stop_loss_points > 0 else None
            )
            self.target_price = (
                self.entry_price + self.p.take_profit_points * self.p.point
                if self.p.take_profit_points > 0 else None
            )
            self.pending_entry_direction = 0
            return

        if self.pending_entry_direction == -1 and order.issell():
            self.sell_count += 1
            self.entry_price = order.executed.price
            self.stop_price = (
                self.entry_price + self.p.stop_loss_points * self.p.point
                if self.p.stop_loss_points > 0 else None
            )
            self.target_price = (
                self.entry_price - self.p.take_profit_points * self.p.point
                if self.p.take_profit_points > 0 else None
            )
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
