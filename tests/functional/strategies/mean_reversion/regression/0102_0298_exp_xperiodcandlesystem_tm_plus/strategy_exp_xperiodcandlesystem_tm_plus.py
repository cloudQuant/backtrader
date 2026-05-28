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


class XPeriodCandleColor(bt.Indicator):
    lines = ('color_idx', 'upper', 'lower', 'xopen', 'xclose')
    params = dict(period=5, bb_length=20, bands_deviation=1.001)

    def __init__(self):
        self.smooth_open = bt.indicators.SimpleMovingAverage(self.data.open, period=self.p.period)
        self.smooth_high = bt.indicators.SimpleMovingAverage(self.data.high, period=self.p.period)
        self.smooth_low = bt.indicators.SimpleMovingAverage(self.data.low, period=self.p.period)
        self.smooth_close = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.period)
        self.mid = bt.indicators.SimpleMovingAverage(self.smooth_close, period=self.p.bb_length)
        self.std = bt.indicators.StandardDeviation(self.smooth_close, period=self.p.bb_length)

    def next(self):
        xopen = float(self.smooth_open[0])
        xclose = float(self.smooth_close[0])
        upper = float(self.mid[0] + self.std[0] * self.p.bands_deviation)
        lower = float(self.mid[0] - self.std[0] * self.p.bands_deviation)
        color = 2.0
        if xopen <= xclose:
            color = 1.0
        elif xopen > xclose:
            color = 3.0
        if xopen <= xclose and xclose > upper:
            color = 0.0
        if xopen > xclose and xclose < lower:
            color = 4.0
        self.lines.xopen[0] = xopen
        self.lines.xclose[0] = xclose
        self.lines.upper[0] = upper
        self.lines.lower[0] = lower
        self.lines.color_idx[0] = color


class ExpXPeriodCandleSystemTmPlusStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=1000,
        takeprofit_pips=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        time_trade=True,
        hold_minutes=960,
        period=5,
        bb_length=20,
        bands_deviation=1.001,
        signal_bar=1,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[1]
        self.channel = XPeriodCandleColor(
            self.signal_feed,
            period=self.p.period,
            bb_length=self.p.bb_length,
            bands_deviation=self.p.bands_deviation,
        )
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.active_side = None
        self.entry_datetime = None
        self.last_signal_dt = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

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
            self.entry_order, self.stop_order, self.limit_order = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
            self.log(f'OPEN LONG size={size} reason={reason}')
        else:
            sl = price + stop_distance
            tp = price - take_distance
            self.entry_order, self.stop_order, self.limit_order = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
            self.log(f'OPEN SHORT size={size} reason={reason}')

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse=None')

    def next(self):
        if len(self.signal_feed) < self.p.period + self.p.bb_length + self.p.signal_bar + 2:
            return
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            if self.position and self.p.time_trade and self.entry_datetime is not None:
                current_dt = bt.num2date(self.data0_feed.datetime[0])
                if (current_dt - self.entry_datetime).total_seconds() >= self.p.hold_minutes * 60:
                    self._submit_close('time based exit')
            return
        self.last_signal_dt = signal_dt
        if self.position and self.p.time_trade and self.entry_datetime is not None:
            current_dt = bt.num2date(self.data0_feed.datetime[0])
            if (current_dt - self.entry_datetime).total_seconds() >= self.p.hold_minutes * 60:
                self._submit_close('time based exit')
                return
        if self.entry_order is not None or self.close_order is not None:
            return
        color_now = float(self.channel.color_idx[0])
        color_prev = float(self.channel.color_idx[-1])
        buy_open = self.p.buy_pos_open and color_now != 0.0 and color_prev == 0.0
        sell_close = self.p.sell_pos_close and color_prev < 2.0
        sell_open = self.p.sell_pos_open and color_now != 4.0 and color_prev == 4.0
        buy_close = self.p.buy_pos_close and color_prev > 2.0
        if self.position.size > 0 and buy_close:
            self._submit_close('xperiod bearish state close long')
            return
        if self.position.size < 0 and sell_close:
            self._submit_close('xperiod bullish state close short')
            return
        if not self.position:
            if buy_open:
                self._submit_entry('long', 'xperiod leave bullish breakout color')
            elif sell_open:
                self._submit_entry('short', 'xperiod leave bearish breakout color')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_datetime = bt.num2date(self.data0_feed.datetime[0])
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.entry_datetime = None
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.entry_datetime = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
                self.entry_datetime = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
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
            self.entry_datetime = None
