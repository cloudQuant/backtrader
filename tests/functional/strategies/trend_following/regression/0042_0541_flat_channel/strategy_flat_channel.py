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


class FlatChannelStrategy(bt.Strategy):
    params = dict(
        mm=False,
        risk=7.0,
        lots=0.01,
        life_time=86400,
        stddev_period=37,
        flet_bars=2,
        canal_min=610,
        canal_max=1860,
        breakeven=True,
        fibo_tral=0.873,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.stddev = bt.ind.StdDev(self.data.close, period=int(self.p.stddev_period), movav=bt.ind.MovAv.Smoothed, safepow=True)
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
        self.pending_buy = None
        self.pending_sell = None
        self.stop_price = None
        self.take_profit_price = None
        self.losses = 0

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _base_size(self):
        size = float(self.p.lots)
        if self.losses == 1:
            size *= 4.0
        return max(0.01, size)

    def _flat_bars_count(self):
        count = 0
        limit = min(len(self) - 1, 100)
        if limit <= 2:
            return 0
        for i in range(limit):
            if float(self.stddev[-i]) > float(self.stddev[-i - 1]):
                break
            if float(self.stddev[-i]) < float(self.stddev[-i - 1]):
                count += 1
        return count

    def _place_channel_orders(self):
        flat_bars = self._flat_bars_count()
        if flat_bars < int(self.p.flet_bars):
            return
        highs = [float(self.data.high[-i]) for i in range(flat_bars + 1)]
        lows = [float(self.data.low[-i]) for i in range(flat_bars + 1)]
        price_max = max(highs)
        price_min = min(lows)
        channel = price_max - price_min
        if channel < float(self.p.canal_min) * self._point() or channel >= float(self.p.canal_max) * self._point():
            return
        tp_buy = price_max + channel
        tp_sell = price_min - channel
        sl_buy = price_max - 2.0 * channel
        sl_sell = price_min + 2.0 * channel
        size = self._base_size()
        expires_bar = len(self) + max(1, int(float(self.p.life_time) / (30 * 60)))
        self.pending_buy = {
            'entry': self._round(price_max), 'sl': self._round(sl_buy), 'tp': self._round(tp_buy), 'size': size, 'expires': expires_bar,
        }
        self.pending_sell = {
            'entry': self._round(price_min), 'sl': self._round(sl_sell), 'tp': self._round(tp_sell), 'size': size, 'expires': expires_bar,
        }

    def _expire_pending(self):
        if self.pending_buy and len(self) >= int(self.pending_buy['expires']):
            self.pending_buy = None
        if self.pending_sell and len(self) >= int(self.pending_sell['expires']):
            self.pending_sell = None

    def _trigger_pending(self):
        if self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.pending_buy and high >= float(self.pending_buy['entry']):
            self.stop_price = self.pending_buy['sl']
            self.take_profit_price = self.pending_buy['tp']
            self.signal_count += 1
            self.order = self.buy(size=float(self.pending_buy['size']))
            self.pending_buy = None
            self.pending_sell = None
            return
        if self.pending_sell and low <= float(self.pending_sell['entry']):
            self.stop_price = self.pending_sell['sl']
            self.take_profit_price = self.pending_sell['tp']
            self.signal_count += 1
            self.order = self.sell(size=float(self.pending_sell['size']))
            self.pending_buy = None
            self.pending_sell = None

    def _breakeven(self):
        if not bool(self.p.breakeven) or not self.position:
            return
        if self.position.size > 0 and self.take_profit_price is not None:
            level = float(self.position.price) + (float(self.take_profit_price) - float(self.position.price)) * float(self.p.fibo_tral)
            if float(self.data.close[0]) > level:
                self.stop_price = max(float(self.stop_price or -10**9), self._round(float(self.position.price)))
        if self.position.size < 0 and self.take_profit_price is not None:
            level = float(self.position.price) - (float(self.position.price) - float(self.take_profit_price)) * float(self.p.fibo_tral)
            if float(self.data.close[0]) < level:
                self.stop_price = min(float(self.stop_price or 10**9), self._round(float(self.position.price)))

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        self._breakeven()
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
        if len(self) < int(self.p.stddev_period) + int(self.p.flet_bars) + 5:
            return
        self._expire_pending()
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        self._trigger_pending()
        if self.order is not None:
            return
        if self.pending_buy is None and self.pending_sell is None:
            self._place_channel_orders()

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
            self.losses = 0
        else:
            self.loss_count += 1
            self.losses += 1
