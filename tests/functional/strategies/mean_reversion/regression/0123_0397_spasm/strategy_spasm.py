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


class SpasmStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        coefficient=5.0,
        period=24,
        exp=False,
        open_close=False,
        sl_fraction=0.5,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.entry_order = None
        self.close_order = None
        self.pending_side = None
        self.pending_reason = None
        self.pending_stop = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.buy_count = 0
        self.sell_count = 0
        self.trend = None
        self.high_highest = None
        self.low_lowest = None
        self.weights = self._build_weights()

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _build_weights(self):
        val = 2.0 / float(self.p.period)
        inc = 2.0
        out = []
        for _ in range(self.p.period):
            out.append(inc)
            inc -= val
        return out

    def _minimum_bars(self):
        return self.p.period * 3 + 2

    def _calc_vol(self):
        total = 0.0
        for i in range(self.p.period):
            if not self.p.open_close:
                value = (float(self.data0_feed.high[-i]) - float(self.data0_feed.low[-i])) / self.p.point_size
            else:
                value = abs(float(self.data0_feed.open[-i]) - float(self.data0_feed.close[-i])) / self.p.point_size
            if self.p.exp:
                value *= self.weights[i]
            total += value
        res = total / float(self.p.period)
        return 1.0 if res <= 0.0 else res

    def _initialize_state(self):
        if self.trend is not None:
            return
        window = self.p.period * 3
        highs = [float(self.data0_feed.high[-i]) for i in range(window)]
        lows = [float(self.data0_feed.low[-i]) for i in range(window)]
        highest_idx = highs.index(max(highs))
        lowest_idx = lows.index(min(lows))
        self.trend = False if highest_idx < lowest_idx else True
        self.high_highest = max(highs)
        self.low_lowest = min(lows)

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _submit_entry(self, side, reason, stop_price):
        if self.entry_order is not None or self.close_order is not None:
            self.pending_side = side
            self.pending_reason = reason
            self.pending_stop = stop_price
            return
        if self.position.size > 0 and side == 'long':
            return
        if self.position.size < 0 and side == 'short':
            return
        if self.position:
            self.pending_side = side
            self.pending_reason = reason
            self.pending_stop = stop_price
            self._submit_close(f'reverse to {side}: {reason}')
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.stop_price = stop_price
        if side == 'long':
            self.entry_order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN LONG size={size} stop={stop_price:.5f} reason={reason}')
        else:
            self.entry_order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SHORT size={size} stop={stop_price:.5f} reason={reason}')
        self.active_side = side

    def _check_stop(self):
        if not self.position or self.close_order is not None or self.stop_price is None:
            return False
        if self.position.size > 0 and float(self.data0_feed.low[0]) <= self.stop_price:
            self._submit_close(f'volatility stop hit @{self.stop_price:.5f}')
            return True
        if self.position.size < 0 and float(self.data0_feed.high[0]) >= self.stop_price:
            self._submit_close(f'volatility stop hit @{self.stop_price:.5f}')
            return True
        return False

    def next(self):
        if len(self.data0_feed) < self._minimum_bars():
            return
        self._initialize_state()
        if self._check_stop():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        price = float(self.data0_feed.close[0])
        plech = int(self._calc_vol() * self.p.coefficient)
        threshold = plech * self.p.point_size
        if self.high_highest is None or self.low_lowest is None:
            self.high_highest = price
            self.low_lowest = price
        if price > self.high_highest + threshold:
            self.high_highest = price
        if price < self.low_lowest - threshold:
            self.low_lowest = price
        ush_sl = 0.0 if self.p.sl_fraction <= 0 else plech * self.p.sl_fraction
        min_ush_sl = max(1.0, float(self.data0_feed.spread[0]) * 3.0)
        if 0.0 < ush_sl < min_ush_sl:
            ush_sl = min_ush_sl
        stop_distance = ush_sl * self.p.point_size
        if not self.trend and price > self.low_lowest + threshold:
            self.trend = True
            self.high_highest = price
            stop = price - stop_distance if stop_distance > 0 else price - self.p.point_size
            self._submit_entry('long', 'volatility reversal above low band', stop)
        elif self.trend and price < self.high_highest - threshold:
            self.trend = False
            self.low_lowest = price
            stop = price + stop_distance if stop_distance > 0 else price + self.p.point_size
            self._submit_entry('short', 'volatility reversal below high band', stop)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_price = order.executed.price
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self.stop_price = None
                if self.pending_side is not None:
                    side = self.pending_side
                    reason = self.pending_reason
                    stop = self.pending_stop
                    self.pending_side = None
                    self.pending_reason = None
                    self.pending_stop = None
                    self._submit_entry(side, reason, stop)
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
            self.stop_price = None
