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


class DeMarkerIndicator(bt.Indicator):
    """
    DeMarker indicator.
    DeMax = max(High - High[-1], 0)
    DeMin = max(Low[-1] - Low, 0)
    DeMarker = SMA(DeMax, period) / (SMA(DeMax, period) + SMA(DeMin, period))
    """
    lines = ('demarker',)
    params = dict(period=13,)

    def __init__(self):
        self.addminperiod(int(self.p.period) + 2)

    def _demarker_at(self, i, high_array, low_array):
        period = max(1, int(self.p.period))
        if i - period < 0:
            return float('nan')
        demax_sum = 0.0
        demin_sum = 0.0
        for idx in range(i - period + 1, i + 1):
            demax_sum += max(float(high_array[idx]) - float(high_array[idx - 1]), 0.0)
            demin_sum += max(float(low_array[idx - 1]) - float(low_array[idx]), 0.0)
        total = demax_sum + demin_sum
        return demax_sum / total if total else 0.0

    def next(self):
        period = max(1, int(self.p.period))
        demax_sum = 0.0
        demin_sum = 0.0
        for ago in range(period):
            demax_sum += max(float(self.data.high[-ago]) - float(self.data.high[-ago - 1]), 0.0)
            demin_sum += max(float(self.data.low[-ago - 1]) - float(self.data.low[-ago]), 0.0)
        total = demax_sum + demin_sum
        self.lines.demarker[0] = demax_sum / total if total else 0.0

    def once(self, start, end):
        high_array = self.data.high.array
        low_array = self.data.low.array
        demarker_line = self.lines.demarker.array
        while len(demarker_line) < end:
            demarker_line.append(float('nan'))

        actual_end = min(end, len(high_array), len(low_array))
        for i in range(start, actual_end):
            demarker_line[i] = self._demarker_at(i, high_array, low_array)


class DematusStrategy(bt.Strategy):
    """
    0317 Dematus EA — DeMarker indicator strategy.

    Core logic (single-position simplification):
    - BUY: DeMarker[2] < 0.3 AND DeMarker[0] > 0.3 (crosses above 0.3 from oversold)
    - SELL: DeMarker[2] > 0.7 AND DeMarker[0] < 0.7 (crosses below 0.7 from overbought)
    - Single position at a time with SL/trailing stop.
    - After a losing trade, lot size is multiplied by coefficient.

    Note: The original EA supports multi-position accumulation when price moves
    away by a distance threshold. This is simplified to single-position mode
    for backtrader compatibility.
    """
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=999,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        demarker_period=13,
        coefficient=2.0,
        reset_price_after_out=False,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.demarker = DeMarkerIndicator(self.data0, period=self.p.demarker_period)
        self.entry_order = None
        self.close_order = None
        self.pending_side = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None
        self.current_lot = self.p.fixed_lot

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
        else:
            self.stop_price = self.entry_price + self.p.stoploss_pips * ps if self.p.stoploss_pips > 0 else None
        self.limit_price = None

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
        size = max(0.01, float(self.current_lot))
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
        else:
            if self.stop_price is not None and bar_high >= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
        return False

    def next(self):
        if len(self.data0) < self.p.demarker_period + 5:
            return
        self._update_trailing_stop()
        if self._check_exit_thresholds():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        if self.position:
            return

        dm0 = float(self.demarker.demarker[0])
        dm2 = float(self.demarker.demarker[-2])

        # BUY: DeMarker crosses above 0.3 from oversold
        if dm2 < 0.3 and dm0 > 0.3:
            self._submit_entry('long', f'DeMarker cross up 0.3: dm[2]={dm2:.4f} dm[0]={dm0:.4f}')
            return

        # SELL: DeMarker crosses below 0.7 from overbought
        if dm2 > 0.7 and dm0 < 0.7:
            self._submit_entry('short', f'DeMarker cross down 0.7: dm[2]={dm2:.4f} dm[0]={dm0:.4f}')
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
        if trade.pnlcomm < 0:
            new_lot = round(self.current_lot * self.p.coefficient, 2)
            if new_lot > 0:
                self.current_lot = new_lot
        else:
            self.current_lot = self.p.fixed_lot
        if not self.position:
            self.active_side = None
            self.entry_price = None
            self._reset_exit_levels()
