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


class EveningStarStrategy(bt.Strategy):
    params = dict(
        evening_star='sell',
        take_profit=150,
        stop_loss=50,
        shift=1,
        gap=True,
        candle2_type=True,
        candle_sizes=True,
        opposite_signal=True,
        lots=0.1,
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
        self.pending_direction = None
        self.stop_price = None
        self.take_profit_price = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _arm(self, direction, price):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if direction == 'buy':
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None

    def _check_exit(self):
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
        s = int(self.p.shift)
        if len(self) < s + 4:
            return
        if self.order is not None:
            return

        if not self.position and self.pending_direction is not None:
            price = float(self.data.close[0])
            self._arm(self.pending_direction, price)
            self.signal_count += 1
            self.order = self.buy(size=self.p.lots) if self.pending_direction == 'buy' else self.sell(size=self.p.lots)
            self.pending_direction = None
            return

        if self.position:
            self._check_exit()
            return

        r0_open = float(self.data.open[-s])
        r0_close = float(self.data.close[-s])
        r1_open = float(self.data.open[-(s + 1)])
        r1_close = float(self.data.close[-(s + 1)])
        r2_open = float(self.data.open[-(s + 2)])
        r2_close = float(self.data.close[-(s + 2)])

        pattern = r0_open > r0_close and r2_open < r2_close
        if not pattern:
            return
        if self.p.candle_sizes:
            if abs(r0_open - r0_close) < abs(r1_open - r1_close) or abs(r2_open - r2_close) < abs(r1_open - r1_close):
                return
        if self.p.candle2_type:
            if r1_open > r1_close:
                return
        else:
            if r1_close > r1_open:
                return
        if self.p.gap:
            ext_distance = 1 * self._point()
            if r0_open >= r1_close - ext_distance or r1_open <= r2_close + ext_distance:
                return

        desired = str(self.p.evening_star).lower()
        if self.p.opposite_signal:
            if desired == 'buy' and self.position.size < 0:
                self.pending_direction = 'buy'
                self.order = self.close()
                return
            if desired == 'sell' and self.position.size > 0:
                self.pending_direction = 'sell'
                self.order = self.close()
                return
        price = float(self.data.close[0])
        self._arm(desired, price)
        self.signal_count += 1
        self.order = self.buy(size=self.p.lots) if desired == 'buy' else self.sell(size=self.p.lots)

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
