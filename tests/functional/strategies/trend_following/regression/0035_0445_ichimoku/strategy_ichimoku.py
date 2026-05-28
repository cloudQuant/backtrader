from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
    })
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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class IchimokuStrategy(bt.Strategy):
    params = dict(
        lot=0.10,
        stop_loss_buy=100,
        take_profit_buy=300,
        stop_loss_sell=100,
        take_profit_sell=300,
        trailing_stop_buy=50,
        trailing_stop_sell=50,
        trailing_step=5,
        use_trade_hours=False,
        from_hour=0,
        to_hour=23,
        tenkan_sen=9,
        kijun_sen=26,
        senkou_span_b=52,
        point=0.01,
    )

    def __init__(self):
        self.ichimoku = bt.ind.Ichimoku(
            self.data,
            tenkan=self.p.tenkan_sen,
            kijun=self.p.kijun_sen,
            senkou=self.p.senkou_span_b,
        )
        self.order = None
        self.pending_action = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(self.p.kijun_sen, self.p.senkou_span_b) + 2:
            return
        if self.order:
            return

        current_dt = bt.num2date(self.data.datetime[0])
        if self.p.use_trade_hours and not (self.p.from_hour <= current_dt.hour <= self.p.to_hour):
            return

        close_0 = float(self.data.close[0])
        tenkan_0 = self._line_value(self.ichimoku.tenkan_sen, 0)
        kijun_0 = self._line_value(self.ichimoku.kijun_sen, 0)
        span_a_0 = self._line_value(self.ichimoku.senkou_span_a, 0)
        span_b_0 = self._line_value(self.ichimoku.senkou_span_b, 0)
        tenkan_1 = self._line_value(self.ichimoku.tenkan_sen, -1)
        if any(value is None for value in [tenkan_0, kijun_0, span_a_0, span_b_0, tenkan_1]):
            return

        buy_signal = tenkan_1 < kijun_0 and tenkan_0 >= kijun_0 and close_0 > span_b_0
        sell_signal = tenkan_1 > kijun_0 and tenkan_0 <= kijun_0 and close_0 < span_a_0

        if self.position:
            if self._check_exit_levels():
                return
            if self.position.size > 0 and sell_signal:
                self.pending_action = 'close'
                self.order = self.close()
                return
            if self.position.size < 0 and buy_signal:
                self.pending_action = 'close'
                self.order = self.close()
                return
            self._update_trailing(close_0)
            return

        if buy_signal:
            self.pending_action = 'open_long'
            self.order = self.buy(size=self.p.lot)
            return
        if sell_signal:
            self.pending_action = 'open_short'
            self.order = self.sell(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if order.status == bt.Order.Completed:
            if self.pending_action == 'open_long':
                self.buy_count += 1
                self.entry_price = order.executed.price
                self.stop_price = self.entry_price - self.p.stop_loss_buy * self.p.point if self.p.stop_loss_buy else None
                self.take_profit_price = self.entry_price + self.p.take_profit_buy * self.p.point if self.p.take_profit_buy else None
            elif self.pending_action == 'open_short':
                self.sell_count += 1
                self.entry_price = order.executed.price
                self.stop_price = self.entry_price + self.p.stop_loss_sell * self.p.point if self.p.stop_loss_sell else None
                self.take_profit_price = self.entry_price - self.p.take_profit_sell * self.p.point if self.p.take_profit_sell else None
            elif self.pending_action == 'close' and not self.position:
                self._clear_trade_levels()

        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None
            self.pending_action = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self._clear_trade_levels()

    def _check_exit_levels(self):
        high_0 = float(self.data.high[0])
        low_0 = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low_0 <= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high_0 >= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                return True
            return False

        if self.stop_price is not None and high_0 >= self.stop_price:
            self.pending_action = 'close'
            self.order = self.close()
            return True
        if self.take_profit_price is not None and low_0 <= self.take_profit_price:
            self.pending_action = 'close'
            self.order = self.close()
            return True
        return False

    def _update_trailing(self, close_0):
        if self.entry_price is None:
            return
        step = self.p.trailing_step * self.p.point
        if self.position.size > 0 and self.p.trailing_stop_buy:
            trail = self.p.trailing_stop_buy * self.p.point
            if close_0 - self.entry_price > trail + step:
                candidate = close_0 - trail
                if self.stop_price is None or self.stop_price < close_0 - (trail + step):
                    self.stop_price = candidate
        elif self.position.size < 0 and self.p.trailing_stop_sell:
            trail = self.p.trailing_stop_sell * self.p.point
            if self.entry_price - close_0 > trail + step:
                candidate = close_0 + trail
                if self.stop_price is None or self.stop_price > close_0 + (trail + step):
                    self.stop_price = candidate

    def _clear_trade_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    @staticmethod
    def _line_value(line, idx):
        value = float(line[idx])
        if math.isnan(value):
            return None
        return value
