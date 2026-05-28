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


class BollingerBandsNPositionsStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        stop_loss=50,
        take_profit=50,
        trailing_stop=5,
        trailing_step=5,
        max_positions=9,
        bb_bands_period=20,
        bb_bands_shift=0,
        bb_deviation=2.0,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bbands = bt.indicators.BollingerBands(
            self.data.close,
            period=int(self.p.bb_bands_period),
            devfactor=float(self.p.bb_deviation),
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
        self.take_profit_price = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _current_layers(self):
        if not self.position:
            return 0
        return int(round(abs(float(self.position.size)) / float(self.p.lots)))

    def _arm_risk(self, direction, price):
        sl_dist = float(self.p.stop_loss) * self._point()
        tp_dist = float(self.p.take_profit) * self._point()
        if direction == 'buy':
            self.stop_price = self._round(price - sl_dist) if sl_dist > 0 else None
            self.take_profit_price = self._round(price + tp_dist) if tp_dist > 0 else None
        else:
            self.stop_price = self._round(price + sl_dist) if sl_dist > 0 else None
            self.take_profit_price = self._round(price - tp_dist) if tp_dist > 0 else None

    def _check_exit(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.pending_direction = None
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.pending_direction = None
                self.order = self.close()
                return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.pending_direction = None
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.pending_direction = None
                self.order = self.close()
                return

    def _trailing(self):
        if not self.position or self.order is not None or float(self.p.trailing_stop) <= 0:
            return
        ts = float(self.p.trailing_stop) * self._point()
        step = float(self.p.trailing_step) * self._point()
        current = float(self.data.close[0])
        entry = float(self.position.price)
        if self.position.size > 0:
            if current - entry > ts + step:
                new_sl = self._round(current - ts)
                if self.stop_price is None or new_sl > float(self.stop_price) + step:
                    self.stop_price = new_sl
        else:
            if entry - current > ts + step:
                new_sl = self._round(current + ts)
                if self.stop_price is None or new_sl < float(self.stop_price) - step:
                    self.stop_price = new_sl

    def next(self):
        self.bar_num += 1
        if len(self) < int(self.p.bb_bands_period) + 2:
            return
        if self.order is not None:
            return

        if not self.position and self.pending_direction is not None:
            price = float(self.data.close[0])
            self._arm_risk(self.pending_direction, price)
            if self.pending_direction == 'buy':
                self.signal_count += 1
                self.order = self.buy(size=self.p.lots)
            else:
                self.signal_count += 1
                self.order = self.sell(size=self.p.lots)
            self.pending_direction = None
            return

        if self.position:
            self._trailing()
            self._check_exit()
            if self.order is not None:
                return

        upper = float(self.bbands.top[0])
        lower = float(self.bbands.bot[0])
        bid = float(self.data.close[0])
        ask = bid
        layers = self._current_layers()

        if bid > upper:
            if self.position.size < 0:
                self.pending_direction = 'buy'
                self.order = self.close()
                return
            if layers < int(self.p.max_positions):
                price = float(self.data.close[0])
                self._arm_risk('buy', price)
                self.signal_count += 1
                self.order = self.buy(size=self.p.lots)
                return

        if ask < lower:
            if self.position.size > 0:
                self.pending_direction = 'sell'
                self.order = self.close()
                return
            if layers < int(self.p.max_positions):
                price = float(self.data.close[0])
                self._arm_risk('sell', price)
                self.signal_count += 1
                self.order = self.sell(size=self.p.lots)

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
