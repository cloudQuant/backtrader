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
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'tick_volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    out['volume'] = out['tick_volume']
    return out


def compute_ac(frame):
    median = (frame['high'] + frame['low']) / 2.0
    ao = median.rolling(5, min_periods=5).mean() - median.rolling(34, min_periods=34).mean()
    ac = ao - ao.rolling(5, min_periods=5).mean()
    out = frame.copy()
    out['ac'] = ac
    return out.dropna(subset=['ac'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class ACFeed(bt.feeds.PandasData):
    lines = ('ac',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('ac', 6),
    )


class TrendAlexcudV2Strategy(bt.Strategy):
    params = dict(
        stop_loss=20,
        take_profit=30,
        trailing_stop=0,
        lots=0.1,
        open_level=1,
        close_level=1,
        ma_periods=(5, 8, 13, 21, 34),
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.tf1 = self.datas[1]
        self.tf2 = self.datas[2]
        self.tf3 = self.datas[3]
        self.ac1 = self.datas[4]
        self.ac3 = self.datas[5]

        self.ma_tf1 = [bt.indicators.SimpleMovingAverage(self.tf1.close, period=p) for p in self.p.ma_periods]
        self.ma_tf2 = [bt.indicators.SimpleMovingAverage(self.tf2.close, period=p) for p in self.p.ma_periods]
        self.ma_tf3 = [bt.indicators.SimpleMovingAverage(self.tf3.close, period=p) for p in self.p.ma_periods]

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
        self.last_signal_dt = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _set_risk(self, side):
        unit = self._unit()
        price = float(self.base.close[0])
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None

    def _trail(self):
        if not self.position or self.p.trailing_stop <= 0:
            return
        unit = self._unit()
        price = float(self.base.close[0])
        if self.position.size > 0 and price - self.position.price > float(self.p.trailing_stop) * unit:
            new_stop = round(price - float(self.p.trailing_stop) * unit, int(self.p.price_digits))
            if self.stop_price is None or self.stop_price < new_stop:
                self.stop_price = new_stop
        if self.position.size < 0 and self.position.price - price > float(self.p.trailing_stop) * unit:
            new_stop = round(price + float(self.p.trailing_stop) * unit, int(self.p.price_digits))
            if self.stop_price is None or self.stop_price > new_stop:
                self.stop_price = new_stop

    def _ac_vote(self, feed):
        acv = float(feed.ac[0])
        ac1v = float(feed.ac[-1])
        ac2v = float(feed.ac[-2])
        ac3v = float(feed.ac[-3])
        bullish = (ac1v > ac2v and ac2v > ac3v and acv < 0 and acv > ac1v) or (acv > ac1v and ac1v > ac2v and acv > 0)
        bearish = (ac1v < ac2v and ac2v < ac3v and acv > 0 and acv < ac1v) or (acv < ac1v and ac1v < ac2v and acv < 0)
        return 1 if bullish else -1 if bearish else 0

    def _tf_score(self, mas, ac_vote):
        up = 0
        down = 0
        for ma in mas:
            curr = float(ma[0])
            prev = float(ma[-1])
            if curr > prev:
                up += 1
            elif curr < prev:
                down += 1
        if ac_vote > 0:
            up += 1
        elif ac_vote < 0:
            down += 1
        return up * 12.5, down * 12.5

    def _signal(self):
        uitog1, ditog1 = self._tf_score(self.ma_tf1, self._ac_vote(self.ac1))
        uitog2, ditog2 = self._tf_score(self.ma_tf2, 0)
        uitog3, ditog3 = self._tf_score(self.ma_tf3, self._ac_vote(self.ac3))
        signal = 0
        if uitog1 > 50 and uitog2 > 50 and uitog3 > 50:
            signal = 1
        if ditog1 > 50 and ditog2 > 50 and ditog3 > 50:
            signal = -1
        if uitog1 >= 75 and uitog2 >= 75 and uitog3 >= 75:
            signal = 2
        if ditog1 >= 75 and ditog2 >= 75 and ditog3 >= 75:
            signal = -2
        return signal

    def _manage_position(self, signal):
        if not self.position or self.order is not None:
            return False
        if self.position.size > 0 and signal < -int(self.p.close_level):
            self.order = self.close()
            return True
        if self.position.size < 0 and signal > int(self.p.close_level):
            self.order = self.close()
            return True
        self._trail()
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if min(len(self.tf1), len(self.tf2), len(self.tf3), len(self.ac1), len(self.ac3)) < max(self.p.ma_periods) + 5:
            return
        if self.order is not None:
            return
        signal_dt = bt.num2date(self.base.datetime[0])
        signal = self._signal()
        if self.position:
            self._manage_position(signal)
            return
        if self.last_signal_dt == signal_dt:
            return
        if signal > int(self.p.open_level):
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.lots)
            self.last_signal_dt = signal_dt
            return
        if signal < -int(self.p.open_level):
            self.signal_count += 1
            self._set_risk('sell')
            self.order = self.sell(size=self.p.lots)
            self.last_signal_dt = signal_dt

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
