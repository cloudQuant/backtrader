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


class WilliamsPercentR(bt.Indicator):
    lines = ('wpr',)
    params = dict(period=14)

    def __init__(self):
        self.highest = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.lowest = bt.indicators.Lowest(self.data.low, period=self.p.period)
        self.addminperiod(self.p.period)

    def next(self):
        highest = float(self.highest[0])
        lowest = float(self.lowest[0])
        denom = highest - lowest
        if denom == 0.0:
            self.lines.wpr[0] = 0.0
            return
        self.lines.wpr[0] = -100.0 * (highest - float(self.data.close[0])) / denom


class ForexFrausM1Strategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=50,
        takeprofit_pips=150,
        trailing_stop_pips=1,
        trailing_step_pips=1,
        timecontrol=True,
        start_hour=7,
        end_hour=17,
        close_opposite=True,
        wpr_calc_period=360,
        overbought_level=-20.0,
        oversold_level=-80.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.wpr = WilliamsPercentR(self.data0_feed, period=self.p.wpr_calc_period)
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
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

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _apply_trailing(self):
        if not self.position or self.stop_order is None or self.p.trailing_stop_pips <= 0:
            return
        trail = self.p.trailing_stop_pips * self.p.point_size
        step = self.p.trailing_step_pips * self.p.point_size
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
            sl = price - stop_distance if self.p.stoploss_pips else price - 10e6
            tp = price + take_distance if self.p.takeprofit_pips else price + 10e6
            self.entry_order, self.stop_order, self.limit_order = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
            self.active_stop_price = None if self.p.stoploss_pips == 0 else sl
            self.log(f'OPEN LONG size={size} reason={reason}')
        else:
            sl = price + stop_distance if self.p.stoploss_pips else price + 10e6
            tp = price - take_distance if self.p.takeprofit_pips else price - 10e6
            self.entry_order, self.stop_order, self.limit_order = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
            self.active_stop_price = None if self.p.stoploss_pips == 0 else sl
            self.log(f'OPEN SHORT size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse}')

    def next(self):
        self._apply_trailing()
        if len(self.data0_feed) < self.p.wpr_calc_period + 2:
            return
        if not self.position and self.pending_reverse and self.entry_order is None and self.close_order is None:
            side = self.pending_reverse
            self.pending_reverse = None
            self._submit_entry(side, 'reverse after close')
            return
        if not self._new_bar():
            return
        current_dt = bt.num2date(self.data0_feed.datetime[0])
        if self.p.timecontrol and (current_dt.hour < self.p.start_hour or current_dt.hour >= self.p.end_hour):
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        wpr0 = float(self.wpr[0])
        buy_signal = wpr0 <= self.p.oversold_level
        sell_signal = wpr0 >= self.p.overbought_level
        if buy_signal:
            if self.position.size < 0 and self.p.close_opposite:
                self._submit_close('wpr oversold buy signal', reverse='long')
            elif not self.position:
                self._submit_entry('long', 'wpr oversold')
            return
        if sell_signal:
            if self.position.size > 0 and self.p.close_opposite:
                self._submit_close('wpr overbought sell signal', reverse='short')
            elif not self.position:
                self._submit_entry('short', 'wpr overbought')

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
