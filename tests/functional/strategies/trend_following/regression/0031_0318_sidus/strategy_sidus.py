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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class AlligatorIndicator(bt.Indicator):
    """Williams Alligator indicator with Jaw, Teeth, Lips lines."""
    lines = ('jaw', 'teeth', 'lips',)
    params = dict(
        jaw_period=13,
        jaw_shift=8,
        teeth_period=8,
        teeth_shift=5,
        lips_period=5,
        lips_shift=3,
        ma_method='smma',
        applied_price='median',
    )

    def __init__(self):
        src = (self.data.high + self.data.low) / 2.0 if self.p.applied_price == 'median' else self.data.close
        self.l.jaw = bt.indicators.SmoothedMovingAverage(src, period=self.p.jaw_period)
        self.l.teeth = bt.indicators.SmoothedMovingAverage(src, period=self.p.teeth_period)
        self.l.lips = bt.indicators.SmoothedMovingAverage(src, period=self.p.lips_period)


class SidusStrategy(bt.Strategy):
    """
    0318 Sidus EA — Alligator + RSI strategy.

    Logic:
    - Uses Alligator indicator (Jaw, Teeth, Lips) and RSI.
    - BUY: RSI crosses above 50 AND all three Alligator lines are rising
      (diff between bar#1 and bar#2 values > delta for Jaw, Teeth, Lips).
      SL = Low[1] - offset.
    - SELL: RSI crosses below 50 AND all three Alligator lines are falling
      (diff < -delta). SL = High[1] + offset.
    - Optional: close opposite positions on signal.
    - TP and trailing stop support.
    """
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        offset_pips=3,
        takeprofit_pips=75,
        trailing_stop_pips=5,
        trailing_step_pips=15,
        delta=0.00003,
        close_opposite=False,
        # Alligator params
        jaw_period=13,
        jaw_shift=8,
        teeth_period=8,
        teeth_shift=5,
        lips_period=5,
        lips_shift=3,
        ma_method='smma',
        applied_price='median',
        # RSI params
        rsi_period=14,
        rsi_applied_price='close',
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.alligator = AlligatorIndicator(
            self.data0,
            jaw_period=self.p.jaw_period,
            jaw_shift=self.p.jaw_shift,
            teeth_period=self.p.teeth_period,
            teeth_shift=self.p.teeth_shift,
            lips_period=self.p.lips_period,
            lips_shift=self.p.lips_shift,
            ma_method=self.p.ma_method,
            applied_price=self.p.applied_price,
        )
        self.rsi = bt.indicators.RSI(self.data0.close, period=self.p.rsi_period)
        self.entry_order = None
        self.close_order = None
        self.pending_side = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None

    def log(self, text):
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _min_bars(self):
        return max(self.p.jaw_period + self.p.jaw_shift, self.p.teeth_period + self.p.teeth_shift,
                   self.p.lips_period + self.p.lips_shift, self.p.rsi_period) + 5

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None

    def _initialize_exit_levels(self, custom_sl=None):
        if not self.position or self.entry_price is None:
            return
        ps = self.p.point_size
        if custom_sl is not None:
            self.stop_price = custom_sl
        if self.position.size > 0:
            self.limit_price = self.entry_price + self.p.takeprofit_pips * ps if self.p.takeprofit_pips > 0 else None
        else:
            self.limit_price = self.entry_price - self.p.takeprofit_pips * ps if self.p.takeprofit_pips > 0 else None

    def _update_trailing_stop(self):
        if not self.position or self.entry_price is None:
            return
        if self.p.trailing_stop_pips == 0:
            return
        ps = self.p.point_size
        ts = self.p.trailing_stop_pips * ps
        step = self.p.trailing_step_pips * ps
        current = float(self.data0.close[0])
        if self.position.size > 0:
            if current - self.entry_price > ts + step:
                new_sl = current - ts
                if self.stop_price is None or new_sl > self.stop_price:
                    self.stop_price = new_sl
        else:
            if self.entry_price - current > ts + step:
                new_sl = current + ts
                if self.stop_price is None or new_sl < self.stop_price:
                    self.stop_price = new_sl

    def _submit_entry(self, side, reason, custom_sl=None):
        if self.entry_order is not None or self.close_order is not None:
            self.pending_side = side
            self._pending_sl = custom_sl
            return
        if self.position.size > 0 and side == 'long':
            return
        if self.position.size < 0 and side == 'short':
            return
        if self.position:
            self.pending_side = side
            self._pending_sl = custom_sl
            self._submit_close(f'reverse to {side}: {reason}')
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.pending_side = None
        self._pending_sl = custom_sl
        if side == 'long':
            self.entry_order = self.buy(size=size)
            self.log(f'OPEN LONG size={size} reason={reason}')
        else:
            self.entry_order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size} reason={reason}')

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _check_exit_thresholds(self):
        if not self.position or self.entry_price is None or self.close_order is not None:
            return False
        bar_high = float(self.data0.high[0])
        bar_low = float(self.data0.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and bar_low <= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_high >= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        else:
            if self.stop_price is not None and bar_high >= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_low <= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        return False

    def next(self):
        if len(self.data0) < self._min_bars():
            return
        self._update_trailing_stop()
        if self._check_exit_thresholds():
            return
        if self.entry_order is not None or self.close_order is not None:
            return

        ps = self.p.point_size
        delta = self.p.delta
        offset = self.p.offset_pips * ps

        # Alligator line diffs (bar#1 - bar#2)
        diff_jaw = float(self.alligator.jaw[-1]) - float(self.alligator.jaw[-2])
        diff_teeth = float(self.alligator.teeth[-1]) - float(self.alligator.teeth[-2])
        diff_lips = float(self.alligator.lips[-1]) - float(self.alligator.lips[-2])

        # RSI crossover
        rsi_prev = float(self.rsi[-2])
        rsi_curr = float(self.rsi[-1])

        # BUY: RSI crosses above 50 AND all alligator lines rising
        if rsi_prev < 50.0 and rsi_curr > 50.0:
            if diff_jaw > delta and diff_teeth > delta and diff_lips > delta:
                sl = float(self.data0.low[-1]) - offset
                if self.p.close_opposite and self.position.size < 0:
                    self._submit_close('close opposite for buy signal')
                self._submit_entry('long', 'RSI cross above 50 + alligator rising', custom_sl=sl)
                return

        # SELL: RSI crosses below 50 AND all alligator lines falling
        if rsi_prev > 50.0 and rsi_curr < 50.0:
            if diff_jaw < -delta and diff_teeth < -delta and diff_lips < -delta:
                sl = float(self.data0.high[-1]) + offset
                if self.p.close_opposite and self.position.size > 0:
                    self._submit_close('close opposite for sell signal')
                self._submit_entry('short', 'RSI cross below 50 + alligator falling', custom_sl=sl)
                return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_price = order.executed.price
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
                custom_sl = getattr(self, '_pending_sl', None)
                self._pending_sl = None
                self._initialize_exit_levels(custom_sl=custom_sl)
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self._reset_exit_levels()
                if self.pending_side is not None:
                    next_side = self.pending_side
                    self.pending_side = None
                    custom_sl = getattr(self, '_pending_sl', None)
                    self._submit_entry(next_side, 'post-close reversal', custom_sl=custom_sl)
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.entry_price = None
            self._reset_exit_levels()
