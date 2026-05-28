from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import os

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


class ICCIIMAStrategy(bt.Strategy):
    params = dict(
        cci_ma_period=14,
        cci_close_ma_period=14,
        ma_ma_period=9,
        lots=0.1,
        stop_loss=50,
        take_profit=40,
        money_management=False,
        deposit=1000.0,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.cci = bt.indicators.CommodityChannelIndex(self.data, period=int(self.p.cci_ma_period))
        self.cci_close = bt.indicators.CommodityChannelIndex(self.data, period=int(self.p.cci_close_ma_period))
        self.cci_ma = bt.indicators.ExponentialMovingAverage(self.cci, period=15)
        self._debug_once = bool(os.environ.get('BT_ICCI_DEBUG'))
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
        self.current_lot_coeff = 1

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _update_lot_coeff(self):
        if not bool(self.p.money_management):
            self.current_lot_coeff = 1
            return
        deposit = max(float(self.p.deposit), 1.0)
        coeff = int(math.floor(self.broker.getvalue() / deposit))
        coeff = max(1, min(20, coeff))
        self.current_lot_coeff = coeff

    def _lot_size(self):
        self._update_lot_coeff()
        return float(self.p.lots) * float(self.current_lot_coeff)

    def _arm(self, direction, price):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if direction == 'buy':
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
            self.signal_count += 1
            self.order = self.buy(size=self._lot_size())
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None
            self.signal_count += 1
            self.order = self.sell(size=self._lot_size())

    def _check_exit_prices(self):
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
        if self._debug_once:
            inds = getattr(self, '_lineiterators', {}).get(bt.LineIterator.IndType, [])
            print(
                'ICCIDBG strategy_mp=%s len=%s inds=%s cci_mp=%s cci_close_mp=%s cci_ma_mp=%s cci_ma_owner=%s' % (
                    getattr(self, '_minperiod', None),
                    len(self),
                    [(i.__class__.__name__, getattr(i, '_minperiod', None)) for i in inds],
                    getattr(self.cci, '_minperiod', None),
                    getattr(self.cci_close, '_minperiod', None),
                    getattr(self.cci_ma, '_minperiod', None),
                    getattr(getattr(self.cci_ma, '_owner', None), '__class__', type(None)).__name__,
                )
            )
            self._debug_once = False
        self.bar_num += 1
        warmup = max(int(self.p.cci_ma_period), int(self.p.cci_close_ma_period), 15) + 5
        if len(self) < warmup:
            return
        if self.order is not None:
            return

        if not self.position and self.pending_direction is not None:
            self._arm(self.pending_direction, float(self.data.close[0]))
            self.pending_direction = None
            return

        cci_0 = float(self.cci[0])
        cci_2 = float(self.cci[-2])
        cci_close_0 = float(self.cci_close[0])
        cci_close_2 = float(self.cci_close[-2])
        ma_0 = float(self.cci_ma[0])
        ma_2 = float(self.cci_ma[-2])

        signal_close_buy = ((cci_close_2 > 100 and cci_close_0 <= 100) or (cci_0 < ma_0 and cci_2 >= ma_2))
        signal_close_sell = ((cci_close_2 < -100 and cci_close_0 >= -100) or (cci_0 > ma_0 and cci_2 <= ma_2))

        if self.position:
            if self.position.size > 0 and signal_close_buy:
                self.order = self.close()
                return
            if self.position.size < 0 and signal_close_sell:
                self.order = self.close()
                return
            self._check_exit_prices()
            if self.order is not None:
                return

        buy_signal = cci_0 > ma_0 and cci_2 < ma_2
        sell_signal = cci_0 < ma_0 and cci_2 > ma_2

        if buy_signal:
            if self.position.size < 0:
                self.pending_direction = 'buy'
                self.order = self.close()
            elif not self.position:
                self._arm('buy', float(self.data.close[0]))
            return
        if sell_signal:
            if self.position.size > 0:
                self.pending_direction = 'sell'
                self.order = self.close()
            elif not self.position:
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
