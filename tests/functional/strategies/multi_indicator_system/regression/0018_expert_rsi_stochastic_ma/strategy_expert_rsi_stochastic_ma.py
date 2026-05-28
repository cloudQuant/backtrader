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


class ExpertRsiStochasticMAStrategy(bt.Strategy):
    params = dict(
        rsi_period=3,
        rsi_up_level=80,
        rsi_dn_level=20,
        st_k_period=6,
        st_d_period=3,
        st_slowing=3,
        st_up_level=70,
        st_dn_level=30,
        ma_period=150,
        lot=0.01,
        allow_loss=30,
        trailing_stop=30,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ma = bt.indicators.SimpleMovingAverage(self.data.close, period=int(self.p.ma_period))
        self.rsi = bt.indicators.RelativeStrengthIndex(self.data.close, period=int(self.p.rsi_period))
        self.stoch = bt.indicators.StochasticFull(
            self.data,
            period=int(self.p.st_k_period),
            period_dfast=int(self.p.st_d_period),
            period_dslow=int(self.p.st_slowing),
        )
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

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _trail(self):
        if not self.position or self.order is not None or float(self.p.trailing_stop) <= 0:
            return
        ts = float(self.p.trailing_stop) * self._point()
        current = float(self.data.close[0])
        if self.position.size > 0:
            new_sl = self._round(current - ts)
            if self.stop_price is None or new_sl > float(self.stop_price):
                self.stop_price = new_sl
        else:
            new_sl = self._round(current + ts)
            if self.stop_price is None or new_sl < float(self.stop_price):
                self.stop_price = new_sl

    def _check_stop(self):
        if not self.position or self.order is not None or self.stop_price is None:
            return
        if self.position.size > 0 and float(self.data.low[0]) <= float(self.stop_price):
            self.order = self.close(); return
        if self.position.size < 0 and float(self.data.high[0]) >= float(self.stop_price):
            self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.ma_period), int(self.p.st_k_period), int(self.p.rsi_period)) + 5
        if len(self) < warmup:
            return
        if self.order is not None:
            return

        if not self.position and self.pending_direction is not None:
            self.signal_count += 1
            self.order = self.buy(size=float(self.p.lot)) if self.pending_direction == 'buy' else self.sell(size=float(self.p.lot))
            self.pending_direction = None
            return

        ma = float(self.ma[0])
        rsi = float(self.rsi[0])
        st_main = float(self.stoch.percD[0])
        st_signal = float(self.stoch.percDSlow[0])
        close_price = float(self.data.close[0])
        allow_loss = float(self.p.allow_loss) * self._point()

        if self.position:
            entry = float(self.position.price)
            if self.position.size > 0:
                if close_price < entry:
                    if allow_loss == 0:
                        if st_main > float(self.p.st_up_level):
                            self.order = self.close(); return
                    else:
                        if entry - close_price >= allow_loss and st_main > float(self.p.st_dn_level):
                            self.order = self.close(); return
                if close_price >= entry and st_main > float(self.p.st_up_level):
                    if float(self.p.trailing_stop) > 0:
                        self._trail()
                    else:
                        self.order = self.close(); return
            else:
                if close_price > entry:
                    if allow_loss == 0:
                        if st_main < float(self.p.st_dn_level):
                            self.order = self.close(); return
                    else:
                        if close_price - entry >= allow_loss and st_main < float(self.p.st_up_level):
                            self.order = self.close(); return
                if close_price <= entry and st_main < float(self.p.st_dn_level):
                    if float(self.p.trailing_stop) > 0:
                        self._trail()
                    else:
                        self.order = self.close(); return
            self._check_stop()
            if self.order is not None:
                return

        buy_signal = close_price > ma and rsi < float(self.p.rsi_dn_level) and st_main < float(self.p.st_dn_level) and st_signal < float(self.p.st_dn_level)
        sell_signal = close_price < ma and rsi > float(self.p.rsi_up_level) and st_main > float(self.p.st_up_level) and st_signal > float(self.p.st_up_level)

        if buy_signal:
            if self.position.size < 0:
                self.pending_direction = 'buy'
                self.order = self.close()
            elif not self.position:
                self.signal_count += 1
                self.order = self.buy(size=float(self.p.lot))
            return
        if sell_signal:
            if self.position.size > 0:
                self.pending_direction = 'sell'
                self.order = self.close()
            elif not self.position:
                self.signal_count += 1
                self.order = self.sell(size=float(self.p.lot))

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if order.executed.size > 0:
                self.buy_count += 1
            elif order.executed.size < 0:
                self.sell_count += 1
            self.stop_price = None
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
