from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv_with_raymond_levels(filepath, fromdate=None, todate=None, bar_shift_minutes=0, raymond_timeframe='D'):
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
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    daily = df.resample(raymond_timeframe).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
    }).dropna()
    prev_daily = daily.shift(1)
    trade_ss = (prev_daily['high'] + prev_daily['low'] + prev_daily['open'] + prev_daily['close']) / 4.0
    pivot_range = prev_daily['high'] - prev_daily['low']
    levels = pd.DataFrame(index=prev_daily.index)
    levels['trade_ss'] = trade_ss
    levels['etb'] = trade_ss + 0.382 * pivot_range
    levels['ets'] = trade_ss - 0.382 * pivot_range
    levels['tpb1'] = trade_ss + 0.618 * pivot_range
    levels['tps1'] = trade_ss - 0.618 * pivot_range
    levels['tpb2'] = trade_ss + 1.0 * pivot_range
    levels['tps2'] = trade_ss - 1.0 * pivot_range
    levels.index = levels.index.normalize()
    intraday = df.copy()
    intraday['session_date'] = intraday.index.normalize()
    intraday = intraday.join(levels, on='session_date')
    intraday = intraday.drop(columns=['session_date'])
    if fromdate is not None:
        intraday = intraday[intraday.index >= fromdate]
    if todate is not None:
        intraday = intraday[intraday.index <= todate]
    intraday = intraday.dropna(subset=['tps1'])
    return intraday


class RaymondPandasFeed(bt.feeds.PandasData):
    lines = ('trade_ss', 'etb', 'ets', 'tpb1', 'tps1', 'tpb2', 'tps2')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('trade_ss', 6),
        ('etb', 7),
        ('ets', 8),
        ('tpb1', 9),
        ('tps1', 10),
        ('tpb2', 11),
        ('tps2', 12),
    )


class RaymondCloudyDayStrategy(bt.Strategy):
    params = dict(
        raymond_timeframe='D1',
        lot_size=0.01,
        stop_points=500,
        take_profit_points=500,
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        comment='Comment',
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_entries = []
        self.stop_orders = {}
        self.limit_orders = {}

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        lot = min(max(lot, self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def next(self):
        self.bar_num += 1
        if len(self.data) < 2:
            return
        prev_low = float(self.data.low[-1])
        prev_close = float(self.data.close[-1])
        tps1 = float(self.data.tps1[0])
        if not pd.notna(tps1):
            return
        size = self._normalize_lot(self.p.lot_size)
        stop_distance = self.p.stop_points * self.p.point_size
        take_distance = self.p.take_profit_points * self.p.point_size
        if prev_low < tps1 and prev_close > tps1:
            stop_price = round(prev_close - stop_distance, 2)
            limit_price = round(prev_close + take_distance, 2)
            orders = self.buy_bracket(size=size, stopprice=stop_price, limitprice=limit_price)
            entry = orders[0]
            entry.addinfo(kind='entry_long')
            self.pending_entries.append(entry.ref)
            self.stop_orders[entry.ref] = orders[1]
            self.limit_orders[entry.ref] = orders[2]
        if prev_low > tps1 and prev_close < tps1:
            stop_price = round(prev_close + stop_distance, 2)
            limit_price = round(prev_close - take_distance, 2)
            orders = self.sell_bracket(size=size, stopprice=stop_price, limitprice=limit_price)
            entry = orders[0]
            entry.addinfo(kind='entry_short')
            self.pending_entries.append(entry.ref)
            self.stop_orders[entry.ref] = orders[1]
            self.limit_orders[entry.ref] = orders[2]

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
        if order.ref in self.pending_entries and not order.alive():
            self.pending_entries.remove(order.ref)
        if order.status in (order.Canceled, order.Margin, order.Rejected):
            self.stop_orders.pop(order.ref, None)
            self.limit_orders.pop(order.ref, None)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
