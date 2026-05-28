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


class TripleEmaRate(bt.Indicator):
    lines = ('value',)
    params = (('period', 14),)

    def __init__(self):
        self.ema1 = bt.ind.EMA(self.data, period=self.p.period)
        self.ema2 = bt.ind.EMA(self.ema1, period=self.p.period)
        self.ema3 = bt.ind.EMA(self.ema2, period=self.p.period)
        self.addminperiod(self.p.period * 3 + 2)

    def next(self):
        prev = float(self.ema3[-1])
        self.lines.value[0] = (float(self.ema3[0]) - prev) / prev if prev else 0.0


class EATrixStrategy(bt.Strategy):
    params = dict(
        period_ema=14,
        signal_period=8,
        stop_loss=50,
        take_profit=150,
        trailing_stop=10,
        trailing_step=1,
        trade_at_close_bar=True,
        break_even=2,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.trix = TripleEmaRate(self.data.close, period=int(self.p.period_ema))
        self.signal = TripleEmaRate(self.data.close, period=int(self.p.signal_period))
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
        self.pending_direction = None
        self.stop_price = None
        self.take_profit_price = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _signal_pair(self):
        if bool(self.p.trade_at_close_bar):
            idx = -1
            prev = -2
        else:
            idx = 0
            prev = -1
        buy_signal = self.signal[prev] < self.trix[prev] and self.signal[idx] > self.trix[idx]
        sell_signal = self.signal[prev] > self.trix[prev] and self.signal[idx] < self.trix[idx]
        return buy_signal, sell_signal

    def _arm(self, direction, price):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if direction == 'buy':
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
            self.signal_count += 1
            self.order = self.buy(size=float(self.p.lots))
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None
            self.signal_count += 1
            self.order = self.sell(size=float(self.p.lots))

    def _manage_protection(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        be = float(self.p.break_even) * self._point()
        ts = float(self.p.trailing_stop) * self._point()
        step = float(self.p.trailing_step) * self._point()
        if self.position.size > 0:
            if be > 0 and float(self.data.close[0]) - float(self.position.price) > be:
                self.stop_price = max(float(self.stop_price or -10**9), self._round(float(self.position.price)))
            if ts > 0 and float(self.data.close[0]) - float(self.position.price) > ts:
                new_sl = self._round(float(self.data.close[0]) - ts)
                if self.stop_price is None or new_sl > float(self.stop_price) + step:
                    self.stop_price = new_sl
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
        else:
            if be > 0 and float(self.position.price) - float(self.data.close[0]) > be:
                self.stop_price = min(float(self.stop_price or 10**9), self._round(float(self.position.price)))
            if ts > 0 and float(self.position.price) - float(self.data.close[0]) > ts:
                new_sl = self._round(float(self.data.close[0]) + ts)
                if self.stop_price is None or new_sl < float(self.stop_price) - step:
                    self.stop_price = new_sl
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self) < max(int(self.p.period_ema), int(self.p.signal_period)) * 3 + 5:
            return
        if self.order is not None:
            return
        buy_signal, sell_signal = self._signal_pair()

        if not self.position and self.pending_direction is not None:
            direction = self.pending_direction
            self.pending_direction = None
            self._arm(direction, float(self.data.close[0]))
            return

        if self.position:
            if self.position.size > 0 and sell_signal:
                self.pending_direction = 'sell'
                self.order = self.close()
                return
            if self.position.size < 0 and buy_signal:
                self.pending_direction = 'buy'
                self.order = self.close()
                return
            self._manage_protection()
            return

        if buy_signal:
            self._arm('buy', float(self.data.close[0]))
            return
        if sell_signal:
            self._arm('sell', float(self.data.close[0]))

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
