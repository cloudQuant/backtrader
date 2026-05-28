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


class BarsAlligatorStrategy(bt.Strategy):
    params = dict(
        stop_loss_pips=150,
        take_profit_pips=150,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        lot_or_risk='lot',
        volume_or_risk=1.0,
        jaw_period=13,
        jaw_shift=8,
        teeth_period=8,
        teeth_shift=5,
        lips_period=5,
        lips_shift=3,
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        median_price = (self.data0.high + self.data0.low) / 2.0
        self.jaw_ma = bt.indicators.SmoothedMovingAverage(median_price, period=self.p.jaw_period)
        self.teeth_ma = bt.indicators.SmoothedMovingAverage(median_price, period=self.p.teeth_period)
        self.lips_ma = bt.indicators.SmoothedMovingAverage(median_price, period=self.p.lips_period)

        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.current_stop = None
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        lot = min(max(lot, self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def _position_size(self, price, stop_distance):
        if self.p.lot_or_risk.lower() == 'risk':
            risk_cash = self.broker.getvalue() * (self.p.volume_or_risk / 100.0)
            raw_size = risk_cash / max(stop_distance * self.p.contract_multiplier, self.p.point_size)
            return self._normalize_lot(raw_size)
        return self._normalize_lot(self.p.volume_or_risk)

    def _line_value(self, line, shift, ago):
        index = -(shift + ago)
        return float(line[index])

    def _buy_signal(self):
        return self._line_value(self.lips_ma, self.p.lips_shift, 1) >= self._line_value(self.jaw_ma, self.p.jaw_shift, 1) and self._line_value(self.lips_ma, self.p.lips_shift, 2) < self._line_value(self.jaw_ma, self.p.jaw_shift, 2)

    def _sell_signal(self):
        return self._line_value(self.lips_ma, self.p.lips_shift, 1) <= self._line_value(self.jaw_ma, self.p.jaw_shift, 1) and self._line_value(self.lips_ma, self.p.lips_shift, 2) > self._line_value(self.jaw_ma, self.p.jaw_shift, 2)

    def _close_long_signal(self):
        return self._line_value(self.lips_ma, self.p.lips_shift, 1) <= self._line_value(self.teeth_ma, self.p.teeth_shift, 1) and self._line_value(self.lips_ma, self.p.lips_shift, 2) > self._line_value(self.teeth_ma, self.p.teeth_shift, 2)

    def _close_short_signal(self):
        return self._line_value(self.lips_ma, self.p.lips_shift, 1) >= self._line_value(self.teeth_ma, self.p.teeth_shift, 1) and self._line_value(self.lips_ma, self.p.lips_shift, 2) < self._line_value(self.teeth_ma, self.p.teeth_shift, 2)

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
        price = self.data0.close[0]
        stop_distance = self.p.stop_loss_pips * self.p.point_size
        size = self._position_size(price, stop_distance)
        if size <= 0:
            self.log(f'SKIP {side.upper()} size={size}')
            return
        if side == 'long':
            sl = price - stop_distance
            tp = price + self.p.take_profit_pips * self.p.point_size
            orders = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
        else:
            sl = price + stop_distance
            tp = price - self.p.take_profit_pips * self.p.point_size
            orders = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
        self.entry_order, self.stop_order, self.limit_order = orders
        self.current_stop = None
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self._cancel_exit_orders()
        self.current_stop = None
        self.close_order = self.close()
        self.log(f'CLOSE size={self.position.size} reason={reason}')

    def _update_trailing(self):
        if not self.position or self.entry_order is not None or self.close_order is not None:
            return
        trailing_stop = self.p.trailing_stop_pips * self.p.point_size
        trailing_step = self.p.trailing_step_pips * self.p.point_size
        trigger = trailing_stop + trailing_step
        close = self.data0.close[0]

        if self.position.size > 0:
            move = close - self.position.price
            if move <= trigger:
                return
            candidate = close - trailing_stop
            if self.current_stop is None or candidate - self.current_stop >= trailing_step:
                self.current_stop = candidate
                self._cancel_exit_orders()
                self.stop_order = self.sell(size=abs(self.position.size), exectype=bt.Order.Stop, price=candidate)
                tp = self.position.price + self.p.take_profit_pips * self.p.point_size
                self.limit_order = self.sell(size=abs(self.position.size), exectype=bt.Order.Limit, price=tp, oco=self.stop_order)
                self.log(f'TRAIL LONG stop={candidate:.5f}')
            return

        move = self.position.price - close
        if move <= trigger:
            return
        candidate = close + trailing_stop
        if self.current_stop is None or self.current_stop - candidate >= trailing_step:
            self.current_stop = candidate
            self._cancel_exit_orders()
            self.stop_order = self.buy(size=abs(self.position.size), exectype=bt.Order.Stop, price=candidate)
            tp = self.position.price - self.p.take_profit_pips * self.p.point_size
            self.limit_order = self.buy(size=abs(self.position.size), exectype=bt.Order.Limit, price=tp, oco=self.stop_order)
            self.log(f'TRAIL SHORT stop={candidate:.5f}')

    def next(self):
        min_bars = max(self.p.jaw_period + self.p.jaw_shift, self.p.teeth_period + self.p.teeth_shift, self.p.lips_period + self.p.lips_shift) + 3
        bar_num = len(self.data0)
        if bar_num <= 25:
            jaw1 = self._line_value(self.jaw_ma, self.p.jaw_shift, 1)
            jaw2 = self._line_value(self.jaw_ma, self.p.jaw_shift, 2)
            lips1 = self._line_value(self.lips_ma, self.p.lips_shift, 1)
            lips2 = self._line_value(self.lips_ma, self.p.lips_shift, 2)
            dt = bt.num2date(self.data0.datetime[0])
            print(f'BAR {bar_num} {dt} close={self.data0.close[0]:.2f} median={((self.data0.high[0]+self.data0.low[0])/2):.2f} jaw[1]={jaw1:.2f} jaw[2]={jaw2:.2f} lips[1]={lips1:.2f} lips[2]={lips2:.2f}')
        if bar_num <= 30 and bar_num >= 13:
            raw_smma_cur = self.jaw_ma[0]
            raw_smma_prev = self.jaw_ma[-1]
            raw_lips_cur = self.lips_ma[0]
            raw_lips_prev = self.lips_ma[-1]
            dt = bt.num2date(self.data0.datetime[0])
            print(f'SMMA_DEBUG {bar_num} {dt} jaw_ma[0]={raw_smma_cur:.4f} jaw_ma[-1]={raw_smma_prev:.4f} lips_ma[0]={raw_lips_cur:.4f} lips_ma[-1]={raw_lips_prev:.4f}')
        if len(self.data0) < min_bars:
            return

        self._update_trailing()
        if self.entry_order is not None or self.close_order is not None:
            return

        buy_signal = self._buy_signal()
        sell_signal = self._sell_signal()
        close_long_signal = self._close_long_signal()
        close_short_signal = self._close_short_signal()

        if self.position:
            if self.position.size > 0:
                profitable = self.data0.close[0] >= self.position.price
                if close_long_signal and profitable:
                    self._submit_close('close long signal')
            else:
                profitable = self.data0.close[0] <= self.position.price
                if close_short_signal and profitable:
                    self._submit_close('close short signal')
            return

        if buy_signal:
            self._submit_entry('long', 'buy signal')
        elif sell_signal:
            self._submit_entry('short', 'sell signal')

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
                self.stop_order = None
                self.limit_order = None
                self.current_stop = None
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.current_stop = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.current_stop = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.log(f'ENTRY FAILED status={order.getstatusname()}')
                self.entry_order = None
                self.stop_order = None
                self.limit_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FAILED status={order.getstatusname()}')
                self.close_order = None
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
