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


def resample_ohlc(df, rule='1D'):
    out = pd.DataFrame()
    out['open'] = df['open'].resample(rule).first()
    out['high'] = df['high'].resample(rule).max()
    out['low'] = df['low'].resample(rule).min()
    out['close'] = df['close'].resample(rule).last()
    out['volume'] = df['volume'].resample(rule).sum()
    out['openinterest'] = 0
    out = out.dropna()
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class ESkochPendingStrategy(bt.Strategy):
    params = dict(
        lots=0.01,
        take_profit_buy=60,
        stop_loss_buy=10,
        take_profit_sell=60,
        stop_loss_sell=30,
        indenting_high=70,
        indenting_low=70,
        check_trade=True,
        percent_equity=2.2,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.intraday = self.datas[0]
        self.daily = self.datas[1]
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
        self.pending_buy = None
        self.pending_sell = None
        self.initial_value = None

    def start(self):
        self.initial_value = self.broker.getvalue()

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _equity_target_reached(self):
        if self.initial_value is None:
            return False
        return self.broker.getvalue() >= self.initial_value * (1.0 + float(self.p.percent_equity) / 100.0)

    def _place_or_update_pending(self):
        if len(self.intraday) < 3 or len(self.daily) < 3:
            return
        if bool(self.p.check_trade) and self.position:
            return
        high_2 = float(self.intraday.high[-2])
        high_1 = float(self.intraday.high[-1])
        high_2_d1 = float(self.daily.high[-2])
        high_1_d1 = float(self.daily.high[-1])
        low_2 = float(self.intraday.low[-2])
        low_1 = float(self.intraday.low[-1])
        low_2_d1 = float(self.daily.low[-2])
        low_1_d1 = float(self.daily.low[-1])
        if high_2_d1 > high_1_d1 and high_2 > high_1:
            entry = high_1 + float(self.p.indenting_high) * self._point()
            sl = entry - float(self.p.stop_loss_buy) * self._point()
            tp = entry + float(self.p.take_profit_buy) * self._point()
            if self.pending_buy is None or entry < float(self.pending_buy['entry']):
                self.pending_buy = {'entry': self._round(entry), 'sl': self._round(sl), 'tp': self._round(tp)}
        if low_2_d1 < low_1_d1 and low_2 < low_1:
            entry = low_1 - float(self.p.indenting_low) * self._point()
            sl = entry + float(self.p.stop_loss_sell) * self._point()
            tp = entry - float(self.p.take_profit_sell) * self._point()
            if self.pending_sell is None or entry > float(self.pending_sell['entry']):
                self.pending_sell = {'entry': self._round(entry), 'sl': self._round(sl), 'tp': self._round(tp)}

    def _trigger_pending(self):
        if self.position or self.order is not None:
            return
        high = float(self.intraday.high[0])
        low = float(self.intraday.low[0])
        if self.pending_buy and high >= float(self.pending_buy['entry']):
            self.stop_price = self.pending_buy['sl']
            self.take_profit_price = self.pending_buy['tp']
            self.signal_count += 1
            self.order = self.buy(size=float(self.p.lots))
            self.pending_buy = None
            self.pending_sell = None
            return
        if self.pending_sell and low <= float(self.pending_sell['entry']):
            self.stop_price = self.pending_sell['sl']
            self.take_profit_price = self.pending_sell['tp']
            self.signal_count += 1
            self.order = self.sell(size=float(self.p.lots))
            self.pending_buy = None
            self.pending_sell = None

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.intraday.high[0])
        low = float(self.intraday.low[0])
        if self._equity_target_reached():
            self.order = self.close(); return
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
        if len(self.intraday) < 3 or len(self.daily) < 3 or self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        self._trigger_pending()
        if self.order is not None:
            return
        self._place_or_update_pending()

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
