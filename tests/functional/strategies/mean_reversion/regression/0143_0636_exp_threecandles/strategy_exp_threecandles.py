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


class ThreeCandlesIndicator(bt.Indicator):
    lines = ('signal',)
    params = (
        ('max_bar1', 300),
        ('volume_type', 'tick'),
    )

    def __init__(self):
        self.addminperiod(5)

    def next(self):
        self.lines.signal[0] = 2.0

        chk_vol = True
        range_points = float(self.data.high[-3] - self.data.low[-3])
        point = float(getattr(self.data, '_point_value', 0.01) or 0.01)
        if point > 0 and range_points / point > float(self.p.max_bar1):
            chk_vol = False

        bullish_setup = (
            float(self.data.open[-3]) < float(self.data.close[-3]) and
            float(self.data.open[-2]) < float(self.data.close[-2]) and
            float(self.data.close[-2]) < float(self.data.high[-3]) and
            float(self.data.open[-1]) > float(self.data.close[-1]) and
            float(self.data.close[-1]) < float(self.data.open[-2])
        )
        bearish_setup = (
            float(self.data.open[-3]) > float(self.data.close[-3]) and
            float(self.data.open[-2]) > float(self.data.close[-2]) and
            float(self.data.close[-2]) > float(self.data.low[-3]) and
            float(self.data.open[-1]) < float(self.data.close[-1]) and
            float(self.data.close[-1]) > float(self.data.open[-2])
        )

        vol_series = self.data.volume

        def volume_filter_ok():
            if not chk_vol or self.p.volume_type == 'none':
                return True
            v3 = float(vol_series[-3])
            v2 = float(vol_series[-2])
            v1 = float(vol_series[-1])
            return v3 < v2 or v1 > v2 or v1 > v3

        if bullish_setup and volume_filter_ok():
            self.lines.signal[0] = 0.0 if float(self.data.close[0]) < float(self.data.open[0]) else 1.0
        if bearish_setup and volume_filter_ok():
            self.lines.signal[0] = 3.0 if float(self.data.close[0]) < float(self.data.open[0]) else 4.0


class ExpThreeCandlesStrategy(bt.Strategy):
    params = dict(
        stop_loss=1000,
        take_profit=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        signal_bar=1,
        max_bar1=300,
        volume_type='tick',
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.data_main = self.datas[0]
        self.data_main._point_value = float(self.p.point)
        self.signal = ThreeCandlesIndicator(self.data_main, max_bar1=self.p.max_bar1, volume_type=self.p.volume_type)

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
        self.pending_reentry_side = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _signal_value(self):
        idx = 1 - int(self.p.signal_bar)
        return float(self.signal[idx])

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

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

    def next(self):
        self.bar_num += 1
        if len(self) < 5:
            return
        if self.order is not None:
            return

        signal_value = self._signal_value()
        buy_signal = signal_value > 2 and self.p.buy_pos_open
        sell_signal = signal_value < 2 and self.p.sell_pos_open
        price = float(self.data.close[0])

        if self.position:
            if self.position.size > 0 and sell_signal and self.p.buy_pos_close:
                self.pending_reentry_side = 'sell'
                self.order = self.close()
                return
            if self.position.size < 0 and buy_signal and self.p.sell_pos_close:
                self.pending_reentry_side = 'buy'
                self.order = self.close()
                return
            self._manage_position()
            return

        if self.pending_reentry_side == 'buy':
            self.pending_reentry_side = None
            self._enter_side('buy', price)
            return
        if self.pending_reentry_side == 'sell':
            self.pending_reentry_side = None
            self._enter_side('sell', price)
            return

        if buy_signal:
            self._enter_side('buy', price)
        elif sell_signal:
            self._enter_side('sell', price)

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
