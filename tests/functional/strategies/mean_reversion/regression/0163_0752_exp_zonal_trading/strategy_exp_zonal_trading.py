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


def awesome_oscillator(frame):
    median = (frame['high'] + frame['low']) / 2.0
    sma5 = median.rolling(5, min_periods=5).mean()
    sma34 = median.rolling(34, min_periods=34).mean()
    ao = sma5 - sma34
    color = (ao.diff() < 0).astype(int)
    out = frame.copy()
    out['signal_state'] = color
    return out.dropna(subset=['signal_state'])


def accelerator_oscillator(frame):
    median = (frame['high'] + frame['low']) / 2.0
    sma5 = median.rolling(5, min_periods=5).mean()
    sma34 = median.rolling(34, min_periods=34).mean()
    ao = sma5 - sma34
    ac = ao - ao.rolling(5, min_periods=5).mean()
    color = (ac.diff() < 0).astype(int)
    out = frame.copy()
    out['signal_state'] = color
    return out.dropna(subset=['signal_state'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class SignalStateFeed(bt.feeds.PandasData):
    lines = ('signal_state',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('signal_state', 6),
    )


class ExpZonalTradingStrategy(bt.Strategy):
    params = dict(
        stop_loss=1000,
        take_profit=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        size=0.1,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.ao = self.datas[1]
        self.ac = self.datas[2]

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
        self.last_signal_dt = None
        self.stop_price = None
        self.take_profit_price = None

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _set_risk(self, side):
        price = float(self.base.close[0])
        unit = self._unit()
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits))
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits))

    def _manage_risk(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if low <= self.stop_price or high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if high >= self.stop_price or low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self._manage_risk():
            return
        signal_dt = bt.num2date(self.ao.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        ao_state = int(self.ao.signal_state[0])
        ac_state = int(self.ac.signal_state[0])
        buy_close = self.p.buy_pos_close and (ao_state < 0 or ac_state < 0)
        sell_close = self.p.sell_pos_close and (ao_state > 0 or ac_state > 0)
        if ao_state == 0 and ac_state == 0:
            if self.position and self.position.size < 0:
                self.order = self.close()
                return
            if not self.position and self.p.buy_pos_open:
                self.signal_count += 1
                self._set_risk('buy')
                self.order = self.buy(size=self.p.size)
                return
        if ao_state == 1 and ac_state == 1:
            if self.position and self.position.size > 0:
                self.order = self.close()
                return
            if not self.position and self.p.sell_pos_open:
                self.signal_count += 1
                self._set_risk('sell')
                self.order = self.sell(size=self.p.size)
                return
        if buy_close and self.position and self.position.size > 0:
            self.order = self.close()
            return
        if sell_close and self.position and self.position.size < 0:
            self.order = self.close()

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
