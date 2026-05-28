from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class MovingAverageCrossoverStrategy(bt.Strategy):
    params = dict(
        use_martingale=True,
        ma_period=50,
        lot_size=0.01,
        tp_points=150,
        sl_points=150,
        starting_lot=0.01,
        max_lot=0.5,
        lot_multiplier=2.0,
        tp_multiplier=2.0,
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
    )

    def __init__(self):
        self.sma = bt.ind.SMA(self.data.close, period=self.p.ma_period)
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.last_trade_profit = None
        self.current_volume = self.p.starting_lot if self.p.use_martingale else self.p.lot_size
        self.current_tp_points = self.p.tp_points
        self.current_sl_points = self.p.sl_points

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        lot = min(max(lot, self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def _prepare_trade_parameters(self):
        if not self.p.use_martingale:
            self.current_volume = self.p.lot_size
            self.current_tp_points = self.p.tp_points
            self.current_sl_points = self.p.sl_points
            return
        if self.last_trade_profit is None:
            self.current_volume = self.p.starting_lot
            self.current_tp_points = self.p.tp_points
            self.current_sl_points = self.p.sl_points
            return
        if self.last_trade_profit < 0 and self.current_volume * self.p.lot_multiplier < self.p.max_lot:
            self.current_volume *= self.p.lot_multiplier
            self.current_tp_points *= self.p.tp_multiplier
            self.current_sl_points *= self.p.tp_multiplier
        elif self.last_trade_profit > 0:
            self.current_volume = self.p.starting_lot
            self.current_tp_points = self.p.tp_points
            self.current_sl_points = self.p.sl_points

    def _crosses_to_sell(self):
        ma_prev = float(self.sma[-1])
        ma_older = float(self.sma[-2])
        prev_close = float(self.data.close[-2])
        current_close = float(self.data.close[-1])
        return ma_prev < prev_close and ma_older > current_close

    def _crosses_to_buy(self):
        ma_prev = float(self.sma[-1])
        ma_older = float(self.sma[-2])
        prev_close = float(self.data.close[-2])
        current_close = float(self.data.close[-1])
        return ma_prev > prev_close and ma_older < current_close

    def next(self):
        self.bar_num += 1
        if len(self.data) <= self.p.ma_period + 2:
            return
        if self.position or self.entry_order is not None:
            return
        self._prepare_trade_parameters()
        size = self._normalize_lot(self.current_volume)
        tp_distance = self.current_tp_points * self.p.point_size
        sl_distance = self.current_sl_points * self.p.point_size
        if self._crosses_to_sell():
            entry_price = float(self.data.close[0])
            stop_price = round(entry_price + sl_distance, 2)
            limit_price = round(entry_price - tp_distance, 2)
            orders = self.sell_bracket(size=size, stopprice=stop_price, limitprice=limit_price)
            self.entry_order, self.stop_order, self.limit_order = orders
            self.entry_order.addinfo(kind='entry_short')
            return
        if self._crosses_to_buy():
            entry_price = float(self.data.close[0])
            stop_price = round(entry_price - sl_distance, 2)
            limit_price = round(entry_price + tp_distance, 2)
            orders = self.buy_bracket(size=size, stopprice=stop_price, limitprice=limit_price)
            self.entry_order, self.stop_order, self.limit_order = orders
            self.entry_order.addinfo(kind='entry_long')

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        kind = getattr(order.info, 'kind', None)
        if order.status == order.Completed:
            if kind == 'entry_long':
                self.buy_count += 1
                self.log(f'long entry price={order.executed.price:.2f} volume={order.executed.size:.4f}')
            elif kind == 'entry_short':
                self.sell_count += 1
                self.log(f'short entry price={order.executed.price:.2f} volume={abs(order.executed.size):.4f}')
        if order is self.entry_order and not order.alive():
            self.entry_order = None
        if order is self.stop_order and not order.alive():
            self.stop_order = None
        if order is self.limit_order and not order.alive():
            self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.last_trade_profit = trade.pnlcomm
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
