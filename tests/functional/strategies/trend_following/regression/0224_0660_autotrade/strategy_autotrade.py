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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
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


class AutotradeStrategy(bt.Strategy):
    params = dict(
        indent=12,
        min_profit=2.0,
        expiration_minutes=41,
        absolute_fixation=43.0,
        stabilization=25,
        lots=0.1,
        point=0.01,
        price_digits=2,
        contract_multiplier=100.0,
    )

    def __init__(self):
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
        self.pending_buy_stop = None
        self.pending_sell_stop = None
        self.pending_expires_at = None
        self.entry_side = None

    def _dt(self):
        return bt.num2date(self.data.datetime[0])

    def _point(self):
        return float(self.p.point)

    def _clear_pending(self):
        self.pending_buy_stop = None
        self.pending_sell_stop = None
        self.pending_expires_at = None

    def _ensure_pending_orders(self):
        if self.position or self.pending_buy_stop is not None or self.pending_sell_stop is not None:
            return
        ask = float(self.data.close[0])
        bid = float(self.data.close[0])
        self.pending_buy_stop = ask + float(self.p.indent) * self._point()
        self.pending_sell_stop = bid - float(self.p.indent) * self._point()
        self.pending_expires_at = self._dt() + pd.Timedelta(minutes=float(self.p.expiration_minutes))

    def _pending_orders_expired(self):
        return self.pending_expires_at is not None and self._dt() >= self.pending_expires_at

    def _check_pending_triggers(self):
        if self.position:
            self._clear_pending()
            return
        if self._pending_orders_expired():
            self._clear_pending()
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.pending_buy_stop is not None and high >= float(self.pending_buy_stop):
            self.signal_count += 1
            self.entry_side = 'buy'
            self.order = self.buy(size=self.p.lots)
            self.pending_sell_stop = None
            return
        if self.pending_sell_stop is not None and low <= float(self.pending_sell_stop):
            self.signal_count += 1
            self.entry_side = 'sell'
            self.order = self.sell(size=self.p.lots)
            self.pending_buy_stop = None

    def _floating_pnl(self):
        if not self.position:
            return 0.0
        return (float(self.data.close[0]) - float(self.position.price)) * float(self.position.size) * float(self.p.contract_multiplier)

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        pnl = self._floating_pnl()
        open1 = float(self.data.open[-1]) if len(self.data) > 1 else float(self.data.open[0])
        close1 = float(self.data.close[-1]) if len(self.data) > 1 else float(self.data.close[0])
        stable_bar = abs(close1 - open1) <= float(self.p.stabilization) * self._point()
        if pnl > float(self.p.min_profit) and stable_bar:
            self.order = self.close()
            self._clear_pending()
            return
        if pnl >= float(self.p.absolute_fixation) or pnl <= -float(self.p.absolute_fixation):
            self.order = self.close()
            self._clear_pending()
            return

    def next(self):
        self.bar_num += 1
        if len(self) < 3:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        self._ensure_pending_orders()
        self._check_pending_triggers()

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
                self._clear_pending()
            else:
                self.entry_side = None
                self._clear_pending()
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
