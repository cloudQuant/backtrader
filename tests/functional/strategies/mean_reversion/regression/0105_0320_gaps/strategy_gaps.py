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


class GapsStrategy(bt.Strategy):
    """
    0320 Gaps EA — gap trading strategy.

    Logic:
    - On each new bar, compare current bar's open with previous bar's high/low.
    - If open < previous_low - gap_pips → BUY (gap down, expect reversion).
    - If open > previous_high + gap_pips → SELL (gap up, expect reversion).
    - Single position at a time.
    - SL/TP/Trailing stop support.
    """
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=50,
        takeprofit_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        gap_pips=1,
    )

    def __init__(self):
        self.data0 = self.datas[0]
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

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None

    def _initialize_exit_levels(self):
        if not self.position or self.entry_price is None:
            return
        ps = self.p.point_size
        if self.position.size > 0:
            self.stop_price = self.entry_price - self.p.stoploss_pips * ps if self.p.stoploss_pips > 0 else None
            self.limit_price = self.entry_price + self.p.takeprofit_pips * ps if self.p.takeprofit_pips > 0 else None
        else:
            self.stop_price = self.entry_price + self.p.stoploss_pips * ps if self.p.stoploss_pips > 0 else None
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

    def _submit_entry(self, side, reason):
        if self.entry_order is not None or self.close_order is not None:
            self.pending_side = side
            return
        if self.position.size > 0 and side == 'long':
            return
        if self.position.size < 0 and side == 'short':
            return
        if self.position:
            self.pending_side = side
            self._submit_close(f'reverse to {side}: {reason}')
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.pending_side = None
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
        if len(self.data0) < 3:
            return
        self._update_trailing_stop()
        if self._check_exit_thresholds():
            return
        if self.entry_order is not None or self.close_order is not None:
            return

        ps = self.p.point_size
        gap = self.p.gap_pips * ps
        cur_open = float(self.data0.open[0])
        prev_high = float(self.data0.high[-1])
        prev_low = float(self.data0.low[-1])

        # Gap down → BUY
        if cur_open < prev_low - gap:
            self._submit_entry('long', f'gap down: open={cur_open:.5f} < prev_low={prev_low:.5f}-gap={gap:.5f}')
        # Gap up → SELL
        elif cur_open > prev_high + gap:
            self._submit_entry('short', f'gap up: open={cur_open:.5f} > prev_high={prev_high:.5f}+gap={gap:.5f}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_price = order.executed.price
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
                self._initialize_exit_levels()
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self._reset_exit_levels()
                if self.pending_side is not None:
                    next_side = self.pending_side
                    self.pending_side = None
                    self._submit_entry(next_side, 'post-close reversal')
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
