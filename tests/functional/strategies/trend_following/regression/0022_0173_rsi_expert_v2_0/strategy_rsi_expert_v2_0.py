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


def get_price_line(data, applied_price):
    value = str(applied_price).lower()
    if value == 'open':
        return data.open
    if value == 'high':
        return data.high
    if value == 'low':
        return data.low
    if value == 'median':
        return (data.high + data.low) / 2.0
    if value == 'typical':
        return (data.high + data.low + data.close) / 3.0
    if value == 'weighted':
        return (data.high + data.low + data.close + data.close) / 4.0
    return data.close


def build_ma(data_line, method, period):
    method_name = str(method).lower()
    if method_name == 'ema':
        return bt.indicators.ExponentialMovingAverage(data_line, period=period)
    if method_name == 'smma':
        return bt.indicators.SmoothedMovingAverage(data_line, period=period)
    if method_name == 'wma':
        return bt.indicators.WeightedMovingAverage(data_line, period=period)
    return bt.indicators.SimpleMovingAverage(data_line, period=period)


class RSIExpertV20Strategy(bt.Strategy):
    params = dict(
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
        mm=1.0,
        mm_mode='lot',
        martingale=True,
        stoploss_pips=50,
        takeprofit_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        ma_trade='forward',
        ma_fast_period=50,
        ma_fast_method='sma',
        ma_fast_applied_price='close',
        ma_slow_period=200,
        ma_slow_method='sma',
        ma_slow_applied_price='close',
        rsi_period=21,
        rsi_level_up=70.0,
        rsi_level_down=30.0,
        rsi_applied_price='close',
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.rsi = bt.indicators.RSI(get_price_line(self.data0_feed, self.p.rsi_applied_price), period=self.p.rsi_period)
        self.ma_fast = build_ma(get_price_line(self.data0_feed, self.p.ma_fast_applied_price), self.p.ma_fast_method, self.p.ma_fast_period)
        self.ma_slow = build_ma(get_price_line(self.data0_feed, self.p.ma_slow_applied_price), self.p.ma_slow_method, self.p.ma_slow_period)
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.pending_reverse = None
        self.active_side = None
        self.active_stop_price = None
        self.closing_side = None
        self.last_trade_was_loss = False
        self.last_bar_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        lot = min(max(float(lot), self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def _size_for_entry(self):
        if str(self.p.mm_mode).lower() == 'risk':
            stop_distance = max(self.p.stoploss_pips * self.p.point_size, self.p.point_size)
            raw = (self.broker.getvalue() * float(self.p.mm)) / max(stop_distance * self.p.contract_multiplier, self.p.point_size)
        else:
            raw = float(self.p.mm)
        if self.p.martingale and self.last_trade_was_loss:
            raw *= 2.0
        return self._normalize_lot(raw)

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
        size = self._size_for_entry()
        if size <= 0:
            return
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
        self.closing_side = self.active_side
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse}')

    def _ma_signal(self):
        mode = str(self.p.ma_trade).lower()
        if mode == 'off':
            return 0
        fast = float(self.ma_fast[0])
        slow = float(self.ma_slow[0])
        if mode == 'forward':
            if fast > slow:
                return 1
            if fast < slow:
                return -1
            return 0
        if fast < slow:
            return 1
        if fast > slow:
            return -1
        return 0

    def _rsi_signal(self):
        current = float(self.rsi[0])
        previous = float(self.rsi[-1])
        if current > self.p.rsi_level_down and previous < self.p.rsi_level_down:
            return 1
        if current < self.p.rsi_level_up and previous > self.p.rsi_level_up:
            return -1
        return 0

    def next(self):
        self.bar_num += 1
        self._apply_trailing()
        required = max(self.p.rsi_period + 2, self.p.ma_slow_period + 1)
        if len(self.data0_feed) < required:
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
        rsi_signal = self._rsi_signal()
        ma_signal = self._ma_signal()
        side_signal = 0
        if rsi_signal == 1 and (ma_signal == 1 or str(self.p.ma_trade).lower() == 'off'):
            side_signal = 1
        elif rsi_signal == -1 and (ma_signal == -1 or str(self.p.ma_trade).lower() == 'off'):
            side_signal = -1
        if side_signal == 1:
            if self.position.size < 0:
                self._submit_close('rsi+ma buy signal', reverse='long')
            elif not self.position:
                self._submit_entry('long', 'rsi crossed above lower level')
            return
        if side_signal == -1:
            if self.position.size > 0:
                self._submit_close('rsi+ma sell signal', reverse='short')
            elif not self.position:
                self._submit_entry('short', 'rsi crossed below upper level')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                if order.executed.size > 0:
                    self.buy_count += 1
                else:
                    self.sell_count += 1
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
        self.trade_count += 1
        self.last_trade_was_loss = trade.pnlcomm <= 0
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED side={self.closing_side or self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        self.closing_side = None
        if not self.position:
            self.active_side = None
            self.active_stop_price = None
