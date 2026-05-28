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


class BollingerNPositionsStrategy(bt.Strategy):
    """Bollinger Bands with trailing stop strategy (EA 0600).

    Simplified to single net position from original hedging multi-position design.

    Entry:
      - Bid > Upper Band -> Sell (close any buy first).
      - Ask < Lower Band -> Buy (close any sell first).

    Position management:
      - Fixed SL/TP.
      - Trailing stop with step.
    """

    params = dict(
        bb_period=20,
        bb_shift=0,
        bb_deviation=2.0,
        lots=0.1,
        stop_loss=50,
        take_profit=50,
        trailing_stop=5,
        trailing_step=5,
        point=0.01,
        price_digits=2,
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
        self.stop_price = None
        self.take_profit_price = None
        self.trailing_activated = False
        self.pending_reentry = None

        self.bbands = bt.indicators.BollingerBands(
            self.data.close,
            period=int(self.p.bb_period),
            devfactor=float(self.p.bb_deviation),
        )

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.bb_period) + 2
        if len(self) < warmup:
            return
        if self.order is not None:
            return

        bid = float(self.data.close[0])
        upper = float(self.bbands.top[0])
        lower = float(self.bbands.bot[0])

        if self.position:
            self._check_exit()
            if self.order is not None:
                return

            if self.position.size > 0 and bid > upper:
                self.pending_reentry = 'sell'
                self.order = self.close()
                return
            if self.position.size < 0 and bid < lower:
                self.pending_reentry = 'buy'
                self.order = self.close()
                return
            return

        sell_sig = bid > upper
        buy_sig = bid < lower

        if sell_sig:
            self._open_sell(bid)
        elif buy_sig:
            self._open_buy(bid)

    def _open_buy(self, price):
        self.signal_count += 1
        sl_dist = float(self.p.stop_loss) * self._point()
        tp_dist = float(self.p.take_profit) * self._point()
        self.stop_price = self._round(price - sl_dist) if sl_dist > 0 else None
        self.take_profit_price = self._round(price + tp_dist) if tp_dist > 0 else None
        self.trailing_activated = False
        self.order = self.buy(size=self.p.lots)

    def _open_sell(self, price):
        self.signal_count += 1
        sl_dist = float(self.p.stop_loss) * self._point()
        tp_dist = float(self.p.take_profit) * self._point()
        self.stop_price = self._round(price + sl_dist) if sl_dist > 0 else None
        self.take_profit_price = self._round(price - tp_dist) if tp_dist > 0 else None
        self.trailing_activated = False
        self.order = self.sell(size=self.p.lots)

    def _check_exit(self):
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])

        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
            self._update_trailing_long(close)
        elif self.position.size < 0:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return
            self._update_trailing_short(close)

    def _update_trailing_long(self, price):
        trail_dist = float(self.p.trailing_stop) * self._point()
        step_dist = float(self.p.trailing_step) * self._point()
        if trail_dist <= 0:
            return
        entry_price = float(self.position.price)
        if price - entry_price >= trail_dist:
            new_sl = self._round(price - trail_dist)
            if self.stop_price is None or new_sl > float(self.stop_price) + step_dist:
                self.stop_price = new_sl
                self.trailing_activated = True

    def _update_trailing_short(self, price):
        trail_dist = float(self.p.trailing_stop) * self._point()
        step_dist = float(self.p.trailing_step) * self._point()
        if trail_dist <= 0:
            return
        entry_price = float(self.position.price)
        if entry_price - price >= trail_dist:
            new_sl = self._round(price + trail_dist)
            if self.stop_price is None or new_sl < float(self.stop_price) - step_dist:
                self.stop_price = new_sl
                self.trailing_activated = True

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
                pending = self.pending_reentry
                self.pending_reentry = None
                self.stop_price = None
                self.take_profit_price = None
                if pending and self.order is not None:
                    pass
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.pending_reentry = None
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None
            if self.pending_reentry and not self.position:
                price = float(self.data.close[0])
                if self.pending_reentry == 'buy':
                    self._open_buy(price)
                else:
                    self._open_sell(price)
                self.pending_reentry = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
