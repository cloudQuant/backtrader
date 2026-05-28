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


class IStochasticTradingStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        take_profit=50,
        stop_loss=50,
        trailing_stop=10,
        trailing_step=5,
        max_positions=3,
        gap=7,
        kperiod=5,
        dperiod=3,
        slowing=3,
        zone_buy=30,
        zone_sell=70,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.stoch = bt.indicators.StochasticFull(
            self.data,
            period=int(self.p.kperiod),
            period_dfast=int(self.p.dperiod),
            period_dslow=int(self.p.slowing),
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
        self.stop_price = None
        self.take_profit_price = None
        self.last_layer_price = None
        self.last_layer_size = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _layers(self):
        if not self.position:
            return 0
        count = abs(float(self.position.size)) / max(float(self.p.lots), 1e-9)
        return max(1, int(round(count)))

    def _max_layers_allowed(self):
        value = int(self.p.max_positions)
        return 10 ** 9 if value <= 0 else value

    def _arm(self, direction, price):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if direction == 'buy':
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None

    def _trail(self):
        if not self.position or self.order is not None or float(self.p.trailing_stop) <= 0:
            return
        ts = float(self.p.trailing_stop) * self._point()
        step = float(self.p.trailing_step) * self._point()
        current = float(self.data.close[0])
        if self.position.size > 0:
            new_sl = self._round(current - ts)
            if self.stop_price is None or new_sl > float(self.stop_price) + step:
                self.stop_price = new_sl
        else:
            new_sl = self._round(current + ts)
            if self.stop_price is None or new_sl < float(self.stop_price) - step:
                self.stop_price = new_sl

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
        warmup = max(int(self.p.kperiod), int(self.p.dperiod), int(self.p.slowing)) + 5
        if len(self) < warmup:
            return
        if self.order is not None:
            return

        if self.position:
            self._trail()
            self._check_exit()
            if self.order is not None:
                return

        main_1 = float(self.stoch.percD[-1])
        signal_1 = float(self.stoch.percDSlow[-1])
        current_price = float(self.data.close[0])

        if not self.position:
            if main_1 > signal_1 and signal_1 < float(self.p.zone_buy):
                self._arm('buy', current_price)
                self.signal_count += 1
                self.last_layer_size = float(self.p.lots)
                self.order = self.buy(size=float(self.p.lots))
                return
            if main_1 < signal_1 and signal_1 > float(self.p.zone_sell):
                self._arm('sell', current_price)
                self.signal_count += 1
                self.last_layer_size = float(self.p.lots)
                self.order = self.sell(size=float(self.p.lots))
                return

        if self.position and self._layers() < self._max_layers_allowed() and self.last_layer_price is not None and self.last_layer_size is not None:
            gap = float(self.p.gap) * self._point()
            if self.position.size > 0 and float(self.last_layer_price) - current_price > gap:
                new_size = float(self.last_layer_size) * 2.0
                self._arm('buy', current_price)
                self.signal_count += 1
                self.last_layer_size = new_size
                self.order = self.buy(size=new_size)
                return
            if self.position.size < 0 and current_price - float(self.last_layer_price) > gap:
                new_size = float(self.last_layer_size) * 2.0
                self._arm('sell', current_price)
                self.signal_count += 1
                self.last_layer_size = new_size
                self.order = self.sell(size=new_size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                self.last_layer_price = float(order.executed.price)
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
                self.last_layer_price = None
                self.last_layer_size = None
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
