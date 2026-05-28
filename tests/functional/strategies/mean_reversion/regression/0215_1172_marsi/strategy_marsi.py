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


class EmaRsiVa(bt.Indicator):
    lines = ('value',)
    params = dict(
        rsi_period=14,
        ema_periods=14.0,
        applied_price='close',
    )

    def __init__(self):
        self.price_line = self._resolve_price_line()
        self.rsi = bt.indicators.RSI(self.price_line, period=self.p.rsi_period)
        self.addminperiod(max(2, int(self.p.rsi_period) * 2))

    def _resolve_price_line(self):
        ap = str(self.p.applied_price).lower()
        if ap in ('close', 'price_close'):
            return self.data.close
        if ap in ('open', 'price_open'):
            return self.data.open
        if ap in ('high', 'price_high'):
            return self.data.high
        if ap in ('low', 'price_low'):
            return self.data.low
        if ap in ('median', 'price_median'):
            return (self.data.high + self.data.low) / 2.0
        if ap in ('typical', 'price_typical'):
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if ap in ('weighted', 'price_weighted'):
            return (self.data.high + self.data.low + self.data.close * 2.0) / 4.0
        return self.data.close

    def next(self):
        price = float(self.price_line[0])
        if len(self) == int(self.p.rsi_period) * 2:
            self.lines.value[0] = price
            return

        rsi_value = float(self.rsi[0]) if len(self.rsi) else float('nan')
        if not math.isfinite(rsi_value):
            prev = float(self.lines.value[-1]) if math.isfinite(float(self.lines.value[-1])) else price
            self.lines.value[0] = prev
            return

        rsvoltl = abs(rsi_value - 50.0) + 1.0
        multi = (5.0 + 100.0 / float(self.p.rsi_period)) / (0.06 + 0.92 * rsvoltl + 0.02 * rsvoltl ** 2)
        pdsx = max(1.0, multi * float(self.p.ema_periods))
        alpha = 2.0 / (pdsx + 1.0)

        prev_value = float(self.lines.value[-1])
        if not math.isfinite(prev_value):
            prev_value = float(self.price_line[-1])

        self.lines.value[0] = price * alpha + prev_value * (1.0 - alpha)


class MarsiStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        tp=0.0,
        sl=0.0,
        use_multpl=False,
        max_drawdown=10000.0,
        max_lot=100.0,
        lot_round_digits=2,
        point=0.01,
        slow_rsi_period=310,
        slow_ema_periods=40.0,
        slow_price='close',
        fast_rsi_period=200,
        fast_ema_periods=50.0,
        fast_price='close',
    )

    def __init__(self):
        self.slow = EmaRsiVa(
            self.data,
            rsi_period=self.p.slow_rsi_period,
            ema_periods=self.p.slow_ema_periods,
            applied_price=self.p.slow_price,
        )
        self.fast = EmaRsiVa(
            self.data,
            rsi_period=self.p.fast_rsi_period,
            ema_periods=self.p.fast_ema_periods,
            applied_price=self.p.fast_price,
        )
        self.order = None
        self.pending_entry_side = None
        self.entry_price = None
        self.stop_price = None
        self.take_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _current_lot(self):
        lot = float(self.p.lots)
        if self.p.use_multpl and float(self.p.max_drawdown) > 0:
            lot = float(self.p.lots) * float(self.broker.getvalue()) / float(self.p.max_drawdown)
        lot = round(lot, int(self.p.lot_round_digits))
        lot = min(lot, float(self.p.max_lot))
        return max(lot, 0.01)

    def _set_exit_levels(self, is_long, executed_price):
        self.entry_price = float(executed_price)
        self.stop_price = None
        self.take_price = None
        if float(self.p.sl) > 0:
            distance = float(self.p.sl) * float(self.p.point)
            self.stop_price = self.entry_price - distance if is_long else self.entry_price + distance
        if float(self.p.tp) > 0:
            distance = float(self.p.tp) * float(self.p.point)
            self.take_price = self.entry_price + distance if is_long else self.entry_price - distance

    def _clear_exit_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.take_price = None

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and self.position.size > 0:
                self._set_exit_levels(True, order.executed.price)
            elif order.issell() and self.position.size < 0:
                self._set_exit_levels(False, order.executed.price)
            elif not self.position:
                self._clear_exit_levels()
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            if not self.position:
                self.pending_entry_side = None
        self.order = None

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
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
        if not self.position:
            self._clear_exit_levels()

    def _check_exit_levels(self):
        if not self.position:
            return False
        if self.stop_price is None and self.take_price is None:
            return False

        high = float(self.data.high[0])
        low = float(self.data.low[0])

        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by sl={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by tp={self.take_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by sl={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by tp={self.take_price:.2f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.slow_rsi_period) * 2, int(self.p.fast_rsi_period) * 2) + 1
        if len(self.data) < warmup:
            return
        if self.order:
            return

        if not self.position and self.pending_entry_side:
            lot = self._current_lot()
            if self.pending_entry_side == 'long':
                self.log(f'pending buy lot={lot:.2f}')
                self.order = self.buy(size=lot)
            else:
                self.log(f'pending sell lot={lot:.2f}')
                self.order = self.sell(size=lot)
            self.pending_entry_side = None
            return

        if self._check_exit_levels():
            return

        slow_prev = float(self.slow[-1])
        slow_now = float(self.slow[0])
        fast_prev = float(self.fast[-1])
        fast_now = float(self.fast[0])

        buy_signal = slow_prev > fast_prev and slow_now <= fast_now
        sell_signal = slow_prev < fast_prev and slow_now >= fast_now
        lot = self._current_lot()

        if not self.position:
            if buy_signal:
                self.log(f'buy slow={slow_now:.5f} fast={fast_now:.5f} lot={lot:.2f}')
                self.order = self.buy(size=lot)
                return
            if sell_signal:
                self.log(f'sell slow={slow_now:.5f} fast={fast_now:.5f} lot={lot:.2f}')
                self.order = self.sell(size=lot)
                return
            return

        if self.position.size > 0 and sell_signal:
            self.log(f'reverse long->short slow={slow_now:.5f} fast={fast_now:.5f}')
            self.pending_entry_side = 'short'
            self.order = self.close()
            return

        if self.position.size < 0 and buy_signal:
            self.log(f'reverse short->long slow={slow_now:.5f} fast={fast_now:.5f}')
            self.pending_entry_side = 'long'
            self.order = self.close()
            return
