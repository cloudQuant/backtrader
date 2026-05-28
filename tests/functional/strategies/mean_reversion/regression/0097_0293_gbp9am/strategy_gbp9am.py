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


class GBP9AMStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        look_price_hour=10,
        look_price_minute=0,
        close_hour=18,
        use_close_hour=True,
        takeprofit_pips=40,
        distance_buy_pips=18,
        distance_sell_pips=22,
        stoploss_buy_pips=22,
        stoploss_sell_pips=18,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.buy_stop_order = None
        self.sell_stop_order = None
        self.close_order = None
        self.clear_to_send = True
        self.last_day = None
        self.active_side = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _cancel_pending(self):
        if self.buy_stop_order is not None:
            self.cancel(self.buy_stop_order)
            self.buy_stop_order = None
        if self.sell_stop_order is not None:
            self.cancel(self.sell_stop_order)
            self.sell_stop_order = None

    def _close_all(self, reason):
        self._cancel_pending()
        if self.position and self.close_order is None:
            self.close_order = self.close()
            self.log(f'CLOSE side={self.active_side} reason={reason} reverse=None')

    def _place_daily_breakout_orders(self):
        self._close_all('preparing daily breakout orders')
        size = max(0.01, float(self.p.fixed_lot))
        ask_price = float(self.data0_feed.close[0])
        bid_price = float(self.data0_feed.close[0])
        buy_price = ask_price + self.p.distance_buy_pips * self.p.point_size
        sell_price = bid_price - self.p.distance_sell_pips * self.p.point_size
        buy_sl = buy_price - self.p.stoploss_buy_pips * self.p.point_size if self.p.stoploss_buy_pips else None
        buy_tp = buy_price + self.p.takeprofit_pips * self.p.point_size if self.p.takeprofit_pips else None
        sell_sl = sell_price + self.p.stoploss_sell_pips * self.p.point_size if self.p.stoploss_sell_pips else None
        sell_tp = sell_price - self.p.takeprofit_pips * self.p.point_size if self.p.takeprofit_pips else None
        self.buy_stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=buy_price)
        self.sell_stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=sell_price)
        self.buy_stop_meta = {'sl': buy_sl, 'tp': buy_tp}
        self.sell_stop_meta = {'sl': sell_sl, 'tp': sell_tp}
        self.log(f'PLACE BUY STOP price={buy_price:.5f} sl={buy_sl} tp={buy_tp}')
        self.log(f'PLACE SELL STOP price={sell_price:.5f} sl={sell_sl} tp={sell_tp}')
        self.clear_to_send = False

    def next(self):
        current_dt = bt.num2date(self.data0_feed.datetime[0])
        if self.last_day != current_dt.date():
            self.last_day = current_dt.date()
            self.clear_to_send = True
        if self.p.use_close_hour and current_dt.hour >= self.p.close_hour:
            self._close_all('close hour reached')
            return
        if current_dt.hour == self.p.look_price_hour and current_dt.minute >= self.p.look_price_minute and self.clear_to_send:
            self._place_daily_breakout_orders()
            return
        if current_dt.hour == self.p.look_price_hour - 1 and abs(current_dt.minute - self.p.look_price_minute) < 10:
            self.clear_to_send = True

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.buy_stop_order:
                self.active_side = 'long'
                self.log(f'ENTRY FILLED side=long price={order.executed.price:.5f} size={order.executed.size}')
                if self.sell_stop_order is not None:
                    self.cancel(self.sell_stop_order)
                    self.sell_stop_order = None
                sl = self.buy_stop_meta.get('sl')
                tp = self.buy_stop_meta.get('tp')
                if sl is not None:
                    self.sell(size=abs(order.executed.size), exectype=bt.Order.Stop, price=sl)
                if tp is not None:
                    self.sell(size=abs(order.executed.size), exectype=bt.Order.Limit, price=tp)
                self.buy_stop_order = None
            elif order == self.sell_stop_order:
                self.active_side = 'short'
                self.log(f'ENTRY FILLED side=short price={order.executed.price:.5f} size={order.executed.size}')
                if self.buy_stop_order is not None:
                    self.cancel(self.buy_stop_order)
                    self.buy_stop_order = None
                sl = self.sell_stop_meta.get('sl')
                tp = self.sell_stop_meta.get('tp')
                if sl is not None:
                    self.buy(size=abs(order.executed.size), exectype=bt.Order.Stop, price=sl)
                if tp is not None:
                    self.buy(size=abs(order.executed.size), exectype=bt.Order.Limit, price=tp)
                self.sell_stop_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.buy_stop_order:
                self.buy_stop_order = None
            elif order == self.sell_stop_order:
                self.sell_stop_order = None
            elif order == self.close_order:
                self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
