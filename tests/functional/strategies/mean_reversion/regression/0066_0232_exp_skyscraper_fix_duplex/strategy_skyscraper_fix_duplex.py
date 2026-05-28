from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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


class SkyscraperFixIndicator(bt.Indicator):
    lines = ('up_buffer', 'dn_buffer', 'buy_buffer', 'sell_buffer')
    params = dict(
        length=10,
        kv=0.9,
        percentage=0.0,
        use_high_low=True,
        atr_period=15,
        point_size=0.01,
    )

    def __init__(self):
        self.addminperiod(max(self.p.length, self.p.atr_period) + 2)
        self.atr = bt.indicators.AverageTrueRange(self.data, period=self.p.atr_period)
        self.atr_high = bt.indicators.Highest(self.atr, period=self.p.length)
        self.atr_low = bt.indicators.Lowest(self.atr, period=self.p.length)
        self._prev_smin = None
        self._prev_smax = None
        self._prev_trend = 0

    @staticmethod
    def _nan():
        return float('nan')

    @staticmethod
    def _valid(value):
        return value is not None and math.isfinite(value)

    def next(self):
        up = self._nan()
        dn = self._nan()
        buy = self._nan()
        sell = self._nan()

        if self._prev_smin is None:
            self._prev_smin = float(self.data.close[0])
            self._prev_smax = float(self.data.close[0])
            self._prev_trend = 0
            self.lines.up_buffer[0] = up
            self.lines.dn_buffer[0] = dn
            self.lines.buy_buffer[0] = buy
            self.lines.sell_buffer[0] = sell
            return

        atrmax = float(self.atr_high[0])
        atrmin = float(self.atr_low[0])
        if not math.isfinite(atrmax) or not math.isfinite(atrmin):
            self.lines.up_buffer[0] = up
            self.lines.dn_buffer[0] = dn
            self.lines.buy_buffer[0] = buy
            self.lines.sell_buffer[0] = sell
            return

        step = int(0.5 * self.p.kv * (atrmax + atrmin) / self.p.point_size)
        xstep = step * self.p.point_size
        x2step = 2.0 * xstep

        close = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])

        if self.p.use_high_low:
            smax0 = low + x2step
            smin0 = high - x2step
        else:
            smax0 = close + x2step
            smin0 = close - x2step

        trend0 = self._prev_trend
        if close > self._prev_smax:
            trend0 = 1
        if close < self._prev_smin:
            trend0 = -1

        if trend0 > 0:
            smin0 = max(smin0, self._prev_smin)
            up = smin0
        else:
            smax0 = min(smax0, self._prev_smax)
            dn = smax0

        prev_up = self.lines.up_buffer[-1] if len(self) > 1 else self._nan()
        prev_dn = self.lines.dn_buffer[-1] if len(self) > 1 else self._nan()

        if self._valid(prev_dn) and self._valid(up):
            buy = up
        if self._valid(prev_up) and self._valid(dn):
            sell = dn

        self.lines.up_buffer[0] = up
        self.lines.dn_buffer[0] = dn
        self.lines.buy_buffer[0] = buy
        self.lines.sell_buffer[0] = sell

        self._prev_smin = smin0
        self._prev_smax = smax0
        self._prev_trend = trend0


class SkyscraperFixDuplexStrategy(bt.Strategy):
    params = dict(
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
        long_mm=0.1,
        long_mm_mode='LOT',
        long_stoploss_points=1000,
        long_takeprofit_points=2000,
        long_allow_open=True,
        long_allow_close=True,
        long_length=10,
        long_kv=0.9,
        long_percentage=0.0,
        long_use_high_low=True,
        short_mm=0.1,
        short_mm_mode='LOT',
        short_stoploss_points=1000,
        short_takeprofit_points=2000,
        short_allow_open=True,
        short_allow_close=True,
        short_length=10,
        short_kv=0.9,
        short_percentage=0.0,
        short_use_high_low=True,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]

        self.long_indicator = SkyscraperFixIndicator(
            self.signal_data,
            length=self.p.long_length,
            kv=self.p.long_kv,
            percentage=self.p.long_percentage,
            use_high_low=self.p.long_use_high_low,
            point_size=self.p.point_size,
        )
        self.short_indicator = SkyscraperFixIndicator(
            self.signal_data,
            length=self.p.short_length,
            kv=self.p.short_kv,
            percentage=self.p.short_percentage,
            use_high_low=self.p.short_use_high_low,
            point_size=self.p.point_size,
        )

        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.last_signal_dt = None

        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def prenext(self):
        self.next()

    def log(self, text):
        dt = bt.num2date(self.exec_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        lot = min(max(lot, self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def _size_for_side(self, side):
        if side == 'long':
            mm = self.p.long_mm
            mode = self.p.long_mm_mode
        else:
            mm = self.p.short_mm
            mode = self.p.short_mm_mode

        if mode.upper() == 'LOT':
            return self._normalize_lot(mm)

        price = self.exec_data.close[0]
        notional = self.broker.getvalue() * mm
        raw_size = notional / max(price * self.p.contract_multiplier, self.p.point_size)
        return self._normalize_lot(raw_size)

    @staticmethod
    def _has_value(value):
        return value is not None and math.isfinite(value)

    def _new_signal_bar(self):
        if len(self.signal_data) == 0:
            return False
        current = bt.num2date(self.signal_data.datetime[0])
        if self.last_signal_dt == current:
            return False
        self.last_signal_dt = current
        return True

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _submit_entry(self, side, reason):
        if self.entry_order is not None or self.close_order is not None or self.position:
            return
        size = self._size_for_side(side)
        if size <= 0:
            self.log(f'SKIP {side.upper()} size={size}')
            return
        price = self.exec_data.close[0]
        if side == 'long':
            sl = price - self.p.long_stoploss_points * self.p.point_size
            tp = price + self.p.long_takeprofit_points * self.p.point_size
            orders = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
        else:
            sl = price + self.p.short_stoploss_points * self.p.point_size
            tp = price - self.p.short_takeprofit_points * self.p.point_size
            orders = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
        self.entry_order, self.stop_order, self.limit_order = orders
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE size={self.position.size} reason={reason} reverse={reverse}')

    def next(self):
        if not self._new_signal_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return

        long_open = self._has_value(self.long_indicator.buy_buffer[0]) and self.p.long_allow_open
        long_close = self._has_value(self.long_indicator.dn_buffer[0]) and self.p.long_allow_close
        short_open = self._has_value(self.short_indicator.sell_buffer[0]) and self.p.short_allow_open
        short_close = self._has_value(self.short_indicator.up_buffer[0]) and self.p.short_allow_close

        if self.position:
            if self.position.size > 0 and long_close:
                self._submit_close('long close signal', reverse='short' if short_open else None)
            elif self.position.size < 0 and short_close:
                self._submit_close('short close signal', reverse='long' if long_open else None)
            return

        if long_open:
            self._submit_entry('long', 'buy buffer signal')
        elif short_open:
            self._submit_entry('short', 'sell buffer signal')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order == self.entry_order:
                self.log(f'ENTRY FILLED side={"BUY" if order.isbuy() else "SELL"} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                next_side = self.pending_reverse
                self.pending_reverse = None
                if not self.position and next_side is not None:
                    self._submit_entry(next_side, 'reverse after close')
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.log(f'ENTRY FAILED status={order.getstatusname()}')
                self.entry_order = None
                self.stop_order = None
                self.limit_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FAILED status={order.getstatusname()}')
                self.close_order = None
                self.pending_reverse = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        elif trade.pnlcomm < 0:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
