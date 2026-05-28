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


class TradeInChannelStrategy(bt.Strategy):
    params = dict(
        risk=2.0,
        lots_on_history=True,
        dcf=3,
        days_ago=30,
        ma_period_atr=4,
        r_channel=20,
        trailing_stop=30,
        base_lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=int(self.p.ma_period_atr))
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

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _channel(self):
        size = int(self.p.r_channel)
        highs_1 = list(self.data.high.get(size=size + 1))
        lows_1 = list(self.data.low.get(size=size + 1))
        highs_2 = list(self.data.high.get(size=size + 2))
        lows_2 = list(self.data.low.get(size=size + 2))
        closes_1 = list(self.data.close.get(size=2))
        if len(highs_1) < size + 1 or len(highs_2) < size + 2 or len(closes_1) < 2:
            return None
        resist = max(highs_1[:-1])
        resist_prev = max(highs_2[:-2])
        support = min(lows_1[:-1])
        support_prev = min(lows_2[:-2])
        pivot = (resist + support + float(closes_1[-2])) / 3.0
        return resist, resist_prev, support, support_prev, pivot

    def _lots_optimized(self):
        lot = float(self.p.base_lot)
        if bool(self.p.lots_on_history) and int(self.p.dcf) > 0:
            losses = min(self.loss_count, 10)
            if losses > 1:
                lot = max(lot - lot * losses / float(self.p.dcf), lot * 0.1)
        return lot

    def _trail(self):
        if not self.position or self.order is not None or float(self.p.trailing_stop) <= 0:
            return
        ts = float(self.p.trailing_stop) * self._point()
        current = float(self.data.close[0])
        if self.position.size > 0:
            if current - float(self.position.price) > ts:
                new_sl = self._round(current - ts)
                if self.stop_price is None or new_sl > float(self.stop_price):
                    self.stop_price = new_sl
        else:
            if float(self.position.price) - current > ts:
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
        warmup = max(int(self.p.ma_period_atr), int(self.p.r_channel)) + 5
        if len(self) < warmup:
            return
        if self.order is not None:
            return

        channel = self._channel()
        if channel is None:
            return
        resist, resist_prev, support, support_prev, pivot = channel
        close_1 = float(self.data.close[-1])
        high_1 = float(self.data.high[-1])
        low_1 = float(self.data.low[-1])
        atr_1 = float(self.atr[-1])

        is_open_buy = (high_1 >= resist and resist == resist_prev) or (close_1 < resist and resist == resist_prev and close_1 > pivot)
        is_open_sell = (low_1 <= support and support == support_prev) or (close_1 > support and support == support_prev and close_1 < pivot)
        is_close_buy = high_1 >= resist and resist == resist_prev
        is_close_sell = low_1 <= support and support == support_prev

        if self.position:
            if self.position.size > 0:
                if is_close_buy:
                    self.order = self.close(); return
            else:
                if is_close_sell:
                    self.order = self.close(); return
            self._trail()
            self._check_stop()
            return

        lot = self._lots_optimized()
        if is_open_buy:
            self.stop_price = self._round(resist + atr_1)
            self.signal_count += 1
            self.order = self.sell(size=lot)
            return
        if is_open_sell:
            self.stop_price = self._round(support - atr_1)
            self.signal_count += 1
            self.order = self.buy(size=lot)

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
