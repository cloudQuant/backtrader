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


class BasicCCIRSIStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=125,
        takeprofit_pips=60,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        cci_period=12,
        rsi_period=15,
        rsi_level_up=75.0,
        rsi_level_down=30.0,
        cci_level_up=80.0,
        cci_level_down=-95.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.active_side = None
        self.active_stop_price = None
        self.last_bar_dt = None

    def _safe_cci(self):
        typical_prices = []
        for idx in range(self.p.cci_period):
            typical_prices.append((float(self.data0_feed.high[-idx]) + float(self.data0_feed.low[-idx]) + float(self.data0_feed.close[-idx])) / 3.0)
        tp_now = typical_prices[0]
        tp_sma = sum(typical_prices) / float(len(typical_prices))
        mean_dev = sum(abs(tp - tp_sma) for tp in typical_prices) / float(len(typical_prices))
        if mean_dev <= 1e-12:
            return 0.0
        return (tp_now - tp_sma) / (0.015 * mean_dev)

    def _safe_rsi(self):
        gains = []
        losses = []
        for idx in range(self.p.rsi_period):
            delta = float(self.data0_feed.close[-idx]) - float(self.data0_feed.close[-idx - 1])
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
        avg_gain = sum(gains) / float(len(gains))
        avg_loss = sum(losses) / float(len(losses))
        if avg_loss <= 1e-12:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

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

    def _place_exit_orders(self):
        if not self.position:
            return
        size = abs(self.position.size)
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        if self.position.size > 0:
            stop_price = self.position.price - stop_distance if self.p.stoploss_pips > 0 else None
            take_price = self.position.price + take_distance if self.p.takeprofit_pips > 0 else None
            if stop_price is not None:
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=stop_price)
                self.active_stop_price = stop_price
            if take_price is not None:
                self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=take_price, oco=self.stop_order)
        else:
            stop_price = self.position.price + stop_distance if self.p.stoploss_pips > 0 else None
            take_price = self.position.price - take_distance if self.p.takeprofit_pips > 0 else None
            if stop_price is not None:
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=stop_price)
                self.active_stop_price = stop_price
            if take_price is not None:
                self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=take_price, oco=self.stop_order)

    def _apply_trailing(self):
        if not self.position or self.p.trailing_stop_pips <= 0 or self.p.trailing_step_pips <= 0 or self.entry_order is not None:
            return
        trail_stop = self.p.trailing_stop_pips * self.p.point_size
        trail_step = self.p.trailing_step_pips * self.p.point_size
        price = float(self.data0_feed.close[0])
        size = abs(self.position.size)
        if self.position.size > 0:
            if price - self.position.price <= trail_stop + trail_step:
                return
            candidate = price - trail_stop
            if self.active_stop_price is None or candidate > self.active_stop_price + trail_step:
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=candidate, oco=self.limit_order)
                self.active_stop_price = candidate
        else:
            if self.position.price - price <= trail_stop + trail_step:
                return
            candidate = price + trail_stop
            if self.active_stop_price is None or candidate < self.active_stop_price - trail_step:
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=candidate, oco=self.limit_order)
                self.active_stop_price = candidate

    def next(self):
        self._apply_trailing()
        if len(self.data0_feed) < max(self.p.cci_period, self.p.rsi_period) + 5:
            return
        if not self._new_bar():
            return
        if self.position or self.entry_order is not None:
            return
        cci_value = self._safe_cci()
        rsi_value = self._safe_rsi()
        cci_buy = cci_value > self.p.cci_level_up
        cci_sell = cci_value < self.p.cci_level_down
        rsi_buy = rsi_value > self.p.rsi_level_up
        rsi_sell = rsi_value < self.p.rsi_level_down
        size = max(0.01, float(self.p.fixed_lot))
        if rsi_buy and cci_buy:
            self.entry_order = self.buy(size=size)
            self.log(f'OPEN LONG size={size} reason=RSI and CCI above thresholds')
        elif rsi_sell and cci_sell:
            self.entry_order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size} reason=RSI and CCI below thresholds')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_order = None
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self._place_exit_orders()
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
