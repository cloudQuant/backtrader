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


class PivotZigZagProxy(bt.Indicator):
    lines = ('high0', 'low0', 'high1', 'low1')
    params = dict(depth=12)

    def __init__(self):
        self.addminperiod(self.p.depth * 3)

    def next(self):
        pivots = []
        lookback = min(len(self.data) - 1, self.p.depth * 8)
        for idx in range(2, lookback):
            high = float(self.data.high[-idx])
            low = float(self.data.low[-idx])
            if high >= float(self.data.high[-idx - 1]) and high >= float(self.data.high[-idx + 1]):
                pivots.append(('high', high, idx))
            if low <= float(self.data.low[-idx - 1]) and low <= float(self.data.low[-idx + 1]):
                pivots.append(('low', low, idx))
        pivots.sort(key=lambda item: item[2])
        pivots = pivots[:4]
        highs = [value for kind, value, _ in pivots if kind == 'high']
        lows = [value for kind, value, _ in pivots if kind == 'low']
        self.lines.high0[0] = highs[0] if len(highs) > 0 else 0.0
        self.lines.high1[0] = highs[1] if len(highs) > 1 else 0.0
        self.lines.low0[0] = lows[0] if len(lows) > 0 else 0.0
        self.lines.low1[0] = lows[1] if len(lows) > 1 else 0.0


class JSMASARTradesStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=50,
        takeprofit_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        use_time=True,
        start_hour=19,
        end_hour=22,
        ma_fast_period=55,
        ma_fast_shift=3,
        ma_slow_period=120,
        ma_slow_shift=0,
        sar_step=0.02,
        sar_maximum=0.2,
        zigzag_depth=12,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.fast_ma = bt.indicators.SmoothedMovingAverage(self.data0_feed.close, period=self.p.ma_fast_period)
        self.slow_ma = bt.indicators.SmoothedMovingAverage(self.data0_feed.close, period=self.p.ma_slow_period)
        self.sar = bt.indicators.ParabolicSAR(self.data0_feed, af=self.p.sar_step, afmax=self.p.sar_maximum)
        self.zigzag = PivotZigZagProxy(self.data0_feed, depth=self.p.zigzag_depth)
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.close_order = None
        self.pending_reverse = None
        self.active_side = None
        self.active_stop_price = None
        self.last_bar_dt = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def prenext(self):
        self.next()

    def _new_bar(self):
        current = bt.num2date(self.data0_feed.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _in_time_window(self):
        if not self.p.use_time:
            return True
        current_dt = bt.num2date(self.data0_feed.datetime[0])
        current_hour = current_dt.hour
        return self.p.start_hour <= current_hour <= self.p.end_hour

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _apply_trailing(self):
        if not self.position or self.stop_order is None:
            return
        step = self.p.trailing_step_pips * self.p.point_size
        trail = self.p.trailing_stop_pips * self.p.point_size
        if self.position.size > 0:
            candidate = float(self.data0_feed.close[0]) - trail
            if self.active_stop_price is None or candidate - self.active_stop_price >= step:
                self.cancel(self.stop_order)
                self.stop_order = self.sell(size=self.position.size, exectype=bt.Order.Stop, price=candidate)
                self.active_stop_price = candidate
        else:
            candidate = float(self.data0_feed.close[0]) + trail
            if self.active_stop_price is None or self.active_stop_price - candidate >= step:
                self.cancel(self.stop_order)
                self.stop_order = self.buy(size=abs(self.position.size), exectype=bt.Order.Stop, price=candidate)
                self.active_stop_price = candidate

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        price = float(self.data0_feed.close[0])
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        if side == 'long':
            sl = price - stop_distance
            tp = price + take_distance
            orders = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
            self.active_stop_price = sl
        else:
            sl = price + stop_distance
            tp = price - take_distance
            orders = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
            self.active_stop_price = sl
        self.entry_order, self.stop_order, self.limit_order = orders
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse}')

    def next(self):
        self._apply_trailing()
        if len(self.data0_feed) < self.p.ma_slow_period + 10:
            return
        if not self._in_time_window():
            return
        if not self.position and self.pending_reverse and self.entry_order is None and self.close_order is None:
            side = self.pending_reverse
            self.pending_reverse = None
            self._submit_entry(side, 'reverse after close')
            return
        if not self._new_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        low_0 = float(self.zigzag.low0[0])
        low_1 = float(self.zigzag.low1[0])
        high_0 = float(self.zigzag.high0[0])
        high_1 = float(self.zigzag.high1[0])
        close = float(self.data0_feed.close[0])
        sar = float(self.sar[0])
        fast = float(self.fast_ma[0])
        slow = float(self.slow_ma[0])
        if low_0 > 0 and low_1 > 0 and low_0 > low_1:
            if self.position.size < 0 and close > sar:
                self._submit_close('buy close condition', reverse='long' if fast > slow and close > sar else None)
                return
            if not self.position and close > sar and fast > slow:
                self._submit_entry('long', 'zigzag low rising + fast>slow + close>sar')
                return
        if high_0 > 0 and high_1 > 0 and high_0 < high_1:
            if self.position.size > 0 and close < sar:
                self._submit_close('sell close condition', reverse='short' if fast < slow and close < sar else None)
                return
            if not self.position and close < sar and fast < slow:
                self._submit_entry('short', 'zigzag high falling + fast<slow + close<sar')
                return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.active_stop_price = None
                reverse = self.pending_reverse
                self.pending_reverse = None
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, 'reverse after close')
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.active_stop_price = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
                self.active_stop_price = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                self.pending_reverse = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.active_stop_price = None
