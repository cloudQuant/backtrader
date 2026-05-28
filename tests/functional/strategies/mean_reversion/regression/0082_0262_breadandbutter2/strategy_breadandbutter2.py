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


class SafeADX(bt.Indicator):
    lines = ('adx',)
    params = dict(period=14)

    def __init__(self):
        self.addminperiod(self.p.period + 3)

    def next(self):
        pdm_vals = []
        mdm_vals = []
        tr_vals = []
        for idx in range(self.p.period):
            high0 = float(self.data.high[-idx])
            high1 = float(self.data.high[-idx - 1])
            low0 = float(self.data.low[-idx])
            low1 = float(self.data.low[-idx - 1])
            close1 = float(self.data.close[-idx - 1])
            up_move = high0 - high1
            down_move = low1 - low0
            pdm = up_move if up_move > down_move and up_move > 0 else 0.0
            mdm = down_move if down_move > up_move and down_move > 0 else 0.0
            tr = max(high0 - low0, abs(high0 - close1), abs(low0 - close1))
            pdm_vals.append(pdm)
            mdm_vals.append(mdm)
            tr_vals.append(tr)
        tr_sum = sum(tr_vals)
        if tr_sum <= 1e-12:
            self.lines.adx[0] = 0.0
            return
        pdi = 100.0 * sum(pdm_vals) / tr_sum
        mdi = 100.0 * sum(mdm_vals) / tr_sum
        denom = pdi + mdi
        if denom <= 1e-12:
            self.lines.adx[0] = 0.0
            return
        self.lines.adx[0] = 100.0 * abs(pdi - mdi) / denom


class SafeAMA(bt.Indicator):
    lines = ('ama',)
    params = dict(period=9, fast_period=2, slow_period=30)

    def __init__(self):
        self._prev = None
        self.addminperiod(self.p.period + 3)

    def next(self):
        if len(self) == 0 or self._prev is None:
            self._prev = float(self.data.close[0])
            self.lines.ama[0] = self._prev
            return
        direction = abs(float(self.data.close[0]) - float(self.data.close[-self.p.period]))
        volatility = 0.0
        for idx in range(self.p.period):
            volatility += abs(float(self.data.close[-idx]) - float(self.data.close[-idx - 1]))
        efficiency = 0.0 if volatility <= 1e-12 else direction / volatility
        fast_sc = 2.0 / (self.p.fast_period + 1.0)
        slow_sc = 2.0 / (self.p.slow_period + 1.0)
        smoothing = (efficiency * (fast_sc - slow_sc) + slow_sc) ** 2
        current = self._prev + smoothing * (float(self.data.close[0]) - self._prev)
        self.lines.ama[0] = current
        self._prev = current


class BreadAndButter2Strategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=50,
        takeprofit_pips=50,
        adx_period=14,
        ama_period=9,
        ama_fast_period=2,
        ama_slow_period=30,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.adx = SafeADX(self.data0_feed, period=self.p.adx_period)
        self.ama = SafeAMA(self.data0_feed, period=self.p.ama_period, fast_period=self.p.ama_fast_period, slow_period=self.p.ama_slow_period)
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.active_side = None
        self.closing_side = None
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

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

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
        else:
            sl = price + stop_distance
            tp = price - take_distance
            orders = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
        self.entry_order, self.stop_order, self.limit_order = orders
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self.closing_side = self.active_side
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse}')

    def next(self):
        if len(self.data0_feed) < max(self.p.adx_period, self.p.ama_period) + 5:
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
        adx_0 = float(self.adx.adx[0])
        adx_1 = float(self.adx.adx[-1])
        ama_0 = float(self.ama.ama[0])
        ama_1 = float(self.ama.ama[-1])
        buy_signal = adx_0 < adx_1 and ama_0 > ama_1
        sell_signal = adx_0 > adx_1 and ama_0 < ama_1
        if self.position.size > 0 and sell_signal:
            self._submit_close('sell signal', reverse='short')
            return
        if self.position.size < 0 and buy_signal:
            self._submit_close('buy signal', reverse='long')
            return
        if self.position:
            return
        if buy_signal:
            self._submit_entry('long', 'adx down and ama up')
        elif sell_signal:
            self._submit_entry('short', 'adx up and ama down')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_order = None
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                reverse = self.pending_reverse
                self.pending_reverse = None
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, 'reverse after close')
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
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
        self.log(f'TRADE CLOSED side={self.closing_side or self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.closing_side = None
