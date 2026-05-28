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


class TrueScalperStrategy(bt.Strategy):
    """EA 0649: MA(3) EMA + MA(7) EMA crossover with RSI(2) filter.
    Buy when MA3 > MA7 and RSI confirms bearish-then-bullish.
    Sell when MA3 < MA7 and RSI confirms bullish-then-bearish.
    Breakeven profit lock included.
    """

    params = dict(
        lots=1.0,
        take_profit=44,
        stop_loss=90,
        rsi_value=50,
        rsi_method_a=False,
        rsi_method_b=True,
        abandon_method_a=True,
        abandon_method_b=False,
        abandon=101,
        use_profit_lock=True,
        break_even_trigger=25,
        break_even=3,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ema3 = bt.indicators.EMA(self.data.close, period=3)
        self.ema7 = bt.indicators.EMA(self.data.close, period=7)
        self.rsi = bt.indicators.RSI(self.data.close, period=2)

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
        self.bars_in_trade = 0
        self.pending_reentry_side = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _set_risk(self, side, price):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if side == 'buy':
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None

    def _enter_side(self, side, price):
        self.signal_count += 1
        self._set_risk(side, price)
        if side == 'buy':
            self.order = self.buy(size=self.p.lots)
        else:
            self.order = self.sell(size=self.p.lots)

    def _handle_abandon(self):
        abandon_bars = int(self.p.abandon)
        if abandon_bars <= 0 or self.bars_in_trade != abandon_bars:
            return False
        if self.p.abandon_method_a:
            self.pending_reentry_side = 'sell' if self.position.size > 0 else 'buy'
            self.order = self.close()
            return True
        if self.p.abandon_method_b:
            self.pending_reentry_side = 'signal'
            self.order = self.close()
            return True
        return False

    def _profit_lock(self):
        if not self.p.use_profit_lock or not self.position:
            return
        price = float(self.data.close[0])
        trigger = float(self.p.break_even_trigger) * self._point()
        be_offset = float(self.p.break_even) * self._point()
        if self.position.size > 0:
            entry = float(self.position.price)
            if price >= entry + trigger and entry > (self.stop_price or 0):
                self.stop_price = self._round(entry + be_offset)
        elif self.position.size < 0:
            entry = float(self.position.price)
            if price <= entry - trigger and entry < (self.stop_price or float('inf')):
                self.stop_price = self._round(entry - be_offset)

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
        if len(self) < 8:
            return
        if self.order is not None:
            return
        if self.position:
            self.bars_in_trade += 1
            self._profit_lock()
            if self._handle_abandon():
                return
            self._manage_position()
            return

        price = float(self.data.close[0])
        if self.pending_reentry_side == 'buy':
            self.pending_reentry_side = None
            self._enter_side('buy', price)
            return
        if self.pending_reentry_side == 'sell':
            self.pending_reentry_side = None
            self._enter_side('sell', price)
            return
        if self.pending_reentry_side == 'signal':
            self.pending_reentry_side = None

        ma3 = float(self.ema3[0])
        ma7 = float(self.ema7[0])
        rsi_1 = float(self.rsi[-1])
        rsi_2 = float(self.rsi[-2])
        rsi_val = float(self.p.rsi_value)

        rsi_pos = False
        rsi_neg = False
        if self.p.rsi_method_a:
            rsi_pos = rsi_1 > rsi_val
            rsi_neg = rsi_1 < rsi_val
        if self.p.rsi_method_b:
            rsi_pos = rsi_pos or (rsi_2 < rsi_val and rsi_1 > rsi_val)
            rsi_neg = rsi_neg or (rsi_2 > rsi_val and rsi_1 < rsi_val)

        if ma3 > ma7 + self._point() and rsi_neg:
            self._enter_side('buy', price)
        elif ma3 < ma7 - self._point() and rsi_pos:
            self._enter_side('sell', price)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                self.bars_in_trade = 0
                if order.executed.size > 0: self.buy_count += 1
                elif order.executed.size < 0: self.sell_count += 1
            else:
                self.bars_in_trade = 0
                self.stop_price = None; self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0: self.win_count += 1
        else: self.loss_count += 1
