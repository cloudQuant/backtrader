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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume']
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class DisasterStrategy(bt.Strategy):
    params = dict(
        stop_loss=35,
        take_profit=95,
        trailing_step=3,
        distance=14,
        timeout=180,
        ma_period=590,
        lots=0.01,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ma = bt.ind.SMA(self.data.close, period=int(self.p.ma_period))
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.stop_price = None
        self.take_profit_price = None
        self.pending_buy = None
        self.pending_sell = None
        self.last_action_dt = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _timeout_ok(self):
        current_dt = bt.num2date(self.data.datetime[0])
        if self.last_action_dt is None:
            return True
        return (current_dt - self.last_action_dt).total_seconds() >= int(self.p.timeout)

    def _set_action_time(self):
        self.last_action_dt = bt.num2date(self.data.datetime[0])

    def _update_pending(self):
        if len(self) < int(self.p.ma_period) + 5 or not self._timeout_ok():
            return
        ima = float(self.ma[-1])
        ask = float(self.data.close[0])
        bid = float(self.data.close[0])
        distance = float(self.p.distance) * self._point()
        step = float(self.p.trailing_step) * self._point()
        sl_dist = float(self.p.stop_loss) * self._point()
        tp_dist = float(self.p.take_profit) * self._point()
        if ask - ima > distance:
            self.pending_sell = None
            if self.pending_buy is None:
                entry = ask + step
                self.pending_buy = {'entry': self._round(entry), 'sl': self._round(entry - sl_dist), 'tp': self._round(entry + tp_dist)}
            elif float(self.pending_buy['entry']) - ask < step:
                entry = float(self.pending_buy['entry']) + step
                self.pending_buy = {'entry': self._round(entry), 'sl': self._round(entry - sl_dist), 'tp': self._round(entry + tp_dist)}
            self._set_action_time()
        elif ima - bid > distance:
            self.pending_buy = None
            if self.pending_sell is None:
                entry = bid - step
                self.pending_sell = {'entry': self._round(entry), 'sl': self._round(entry + sl_dist), 'tp': self._round(entry - tp_dist)}
            elif bid - float(self.pending_sell['entry']) < step:
                entry = float(self.pending_sell['entry']) - step
                self.pending_sell = {'entry': self._round(entry), 'sl': self._round(entry + sl_dist), 'tp': self._round(entry - tp_dist)}
            self._set_action_time()

    def _trigger_pending(self):
        if self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.pending_buy and high >= float(self.pending_buy['entry']):
            self.stop_price = self.pending_buy['sl']
            self.take_profit_price = self.pending_buy['tp']
            self.signal_count += 1
            self.order = self.buy(size=float(self.p.lots))
            self.pending_buy = None
            self.pending_sell = None
            return
        if self.pending_sell and low <= float(self.pending_sell['entry']):
            self.stop_price = self.pending_sell['sl']
            self.take_profit_price = self.pending_sell['tp']
            self.signal_count += 1
            self.order = self.sell(size=float(self.p.lots))
            self.pending_buy = None
            self.pending_sell = None

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self) < int(self.p.ma_period) + 5:
            return
        if self.position:
            self._manage_position()
            return
        if self.order is not None:
            return
        self._trigger_pending()
        if self.order is not None:
            return
        self._update_pending()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
