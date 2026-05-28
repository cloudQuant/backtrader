from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader.feeds as btfeeds
import backtrader.functions as btfunc
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


class T3Average(Indicator):
    lines = ('t3',)
    params = dict(period=10, vfactor=0.7)

    def __init__(self):
        period = max(int(self.p.period), 1)
        vfactor = min(max(float(self.p.vfactor), 0.0), 1.0)
        e1 = btind.EMA(self.data, period=period)
        e2 = btind.EMA(e1, period=period)
        e3 = btind.EMA(e2, period=period)
        e4 = btind.EMA(e3, period=period)
        e5 = btind.EMA(e4, period=period)
        e6 = btind.EMA(e5, period=period)

        c1 = -vfactor ** 3
        c2 = 3 * vfactor ** 2 + 3 * vfactor ** 3
        c3 = -6 * vfactor ** 2 - 3 * vfactor - 3 * vfactor ** 3
        c4 = 1 + 3 * vfactor + vfactor ** 3 + 3 * vfactor ** 2
        self.l.t3 = c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3


class T3Trix(Indicator):
    lines = ('fast', 'slow', 'hist')
    params = dict(
        xlength1=10,
        xlength2=18,
        xphase=70,
    )

    def __init__(self):
        vfactor = min(max(float(self.p.xphase) / 100.0, 0.0), 1.0)
        fast_t3 = T3Average(self.data.close, period=int(self.p.xlength1), vfactor=vfactor)
        slow_t3 = T3Average(self.data.close, period=int(self.p.xlength2), vfactor=vfactor)
        self.l.fast = btfunc.DivByZero(fast_t3 - fast_t3(-1), fast_t3(-1), zero=0.0)
        self.l.slow = btfunc.DivByZero(slow_t3 - slow_t3(-1), slow_t3(-1), zero=0.0)
        self.l.hist = self.l.fast


class T3TrixStrategy(Strategy):
    params = dict(
        mode='twist',
        signal_bar=1,
        xlength1=10,
        xlength2=18,
        xphase=70,
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.osc = T3Trix(
            self.data,
            xlength1=self.p.xlength1,
            xlength2=self.p.xlength2,
            xphase=self.p.xphase,
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
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.pending_entry_direction = 0
        self.warmup = max(int(self.p.xlength2) * 8, 60)

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
        hist_now = float(self.osc.hist[current])
        hist_prev = float(self.osc.hist[previous])
        return hist_prev <= 0.0 and hist_now > 0.0, hist_prev >= 0.0 and hist_now < 0.0

    def _twist_signals(self):
        current, previous, older = self._signal_indexes()
        hist_now = float(self.osc.hist[current])
        hist_prev = float(self.osc.hist[previous])
        hist_older = float(self.osc.hist[older])
        return hist_prev < hist_older and hist_now > hist_prev, hist_prev > hist_older and hist_now < hist_prev

    def _cloudtwist_signals(self):
        current, previous, _ = self._signal_indexes()
        fast_now = float(self.osc.fast[current])
        fast_prev = float(self.osc.fast[previous])
        slow_now = float(self.osc.slow[current])
        slow_prev = float(self.osc.slow[previous])
        return fast_prev <= slow_prev and fast_now > slow_now, fast_prev >= slow_prev and fast_now < slow_now

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

    def _close_position(self, reason):
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
                self._close_position(f'close long stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and high >= self.target_price:
                self._close_position(f'close long target={self.target_price:.2f}')
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self._close_position(f'close short stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and low <= self.target_price:
                self._close_position(f'close short target={self.target_price:.2f}')
                return True

        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.warmup + max(int(self.p.signal_bar), 1) + 2:
            return

        if self._manage_protective_levels():
            return

        buy_signal, sell_signal = self._get_signals()
        hist_now = float(self.osc.hist[0])
        fast_now = float(self.osc.fast[0])
        slow_now = float(self.osc.slow[0])

        if buy_signal:
            self.buy_signal_count += 1
        if sell_signal:
            self.sell_signal_count += 1

        if self.position:
            if self.position.size > 0 and sell_signal:
                self.log(f'close long & sell fast={fast_now:.6f} slow={slow_now:.6f} hist={hist_now:.6f}')
                self.close()
                self._reset_levels()
                self._open_short()
                return
            if self.position.size < 0 and buy_signal:
                self.log(f'close short & buy fast={fast_now:.6f} slow={slow_now:.6f} hist={hist_now:.6f}')
                self.close()
                self._reset_levels()
                self._open_long()
                return
        else:
            if buy_signal:
                self.log(f'buy fast={fast_now:.6f} slow={slow_now:.6f} hist={hist_now:.6f}')
                self._open_long()
                return
            if sell_signal:
                self.log(f'sell fast={fast_now:.6f} slow={slow_now:.6f} hist={hist_now:.6f}')
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
