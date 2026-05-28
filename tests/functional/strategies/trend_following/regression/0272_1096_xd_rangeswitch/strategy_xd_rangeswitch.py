from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import numpy as np
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


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def compute_xd_rangeswitch(frame, n=4):
    n = max(int(n), 1)
    high = frame['high'].to_numpy(dtype=float)
    low = frame['low'].to_numpy(dtype=float)
    close = frame['close'].to_numpy(dtype=float)
    up = np.full(len(frame), np.nan, dtype=float)
    down = np.full(len(frame), np.nan, dtype=float)
    up_signal = np.full(len(frame), np.nan, dtype=float)
    down_signal = np.full(len(frame), np.nan, dtype=float)

    for i in range(len(frame)):
        if i < n:
            continue
        prev_high = np.max(high[i - n:i])
        prev_low = np.min(low[i - n:i])
        if close[i] > prev_high:
            down[i] = np.min(low[i - n + 1:i + 1])
        elif close[i] < prev_low:
            up[i] = np.max(high[i - n + 1:i + 1])
        else:
            up[i] = up[i - 1]
            down[i] = down[i - 1]

        if i > 0 and np.isnan(up[i - 1]) and not np.isnan(up[i]):
            up_signal[i] = up[i]
        if i > 0 and np.isnan(down[i - 1]) and not np.isnan(down[i]):
            down_signal[i] = down[i]

    out = frame.copy()
    out['upper_trend'] = up
    out['lower_trend'] = down
    out['sell_signal'] = up_signal
    out['buy_signal'] = down_signal
    return out.dropna(subset=['upper_trend', 'lower_trend'], how='all')


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class XdRangeSwitchFeed(bt.feeds.PandasData):
    lines = ('upper_trend', 'lower_trend', 'sell_signal', 'buy_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('upper_trend', 6), ('lower_trend', 7), ('sell_signal', 8), ('buy_signal', 9),
    )


class XdRangeSwitchStrategy(bt.Strategy):
    params = dict(
        mm=0.1,
        mm_mode='LOT',
        stop_loss=1000,
        take_profit=2000,
        deviation=10,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        direct='FalshDirect',
        n=4,
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h4 = self.datas[1]
        self.upper_trend = self.h4.upper_trend
        self.lower_trend = self.h4.lower_trend
        self.sell_signal = self.h4.sell_signal
        self.buy_signal = self.h4.buy_signal

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.current_side = None
        self.last_signal_dt = None

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _present(self, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        return not math.isnan(v) and v != 0.0

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        values = [
            self.upper_trend[-idx], self.lower_trend[-idx], self.sell_signal[-idx], self.buy_signal[-idx]
        ]
        return any(self._present(v) for v in values)

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.m15.high[0])
        low = float(self.m15.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.entry_order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.entry_order = self.close()
                return True
        return False

    def _set_risk_prices(self, side):
        price = float(self.m15.close[0])
        unit = self._trade_unit()
        if side == 'buy':
            self.stop_price = round(price - self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        self.current_side = side

    def _mapped_buffers(self):
        if str(self.p.direct) == 'TrueDirect':
            return self.lower_trend, self.buy_signal, self.upper_trend, self.sell_signal
        return self.upper_trend, self.sell_signal, self.lower_trend, self.buy_signal

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        up_trend, up_signal, dn_trend, dn_signal = self._mapped_buffers()
        buy_open = buy_close = sell_open = sell_close = False

        if self._present(up_signal[-idx]):
            if self.p.buy_pos_open:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        elif self._present(up_trend[-idx]):
            sell_close = True

        if self._present(dn_signal[-idx]):
            if self.p.sell_pos_open:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        elif self._present(dn_trend[-idx]):
            buy_close = True

        return buy_open, buy_close, sell_open, sell_close

    def next(self):
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return

        signal_dt = bt.num2date(self.h4.datetime[-max(int(self.p.signal_bar), 1)])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        buy_open, buy_close, sell_open, sell_close = self._evaluate_signals()
        self.log('xd-rangeswitch buy_open={0} buy_close={1} sell_open={2} sell_close={3}'.format(buy_open, buy_close, sell_open, sell_close))

        if buy_close and self.position and self.position.size > 0:
            self.entry_order = self.close()
            return
        if sell_close and self.position and self.position.size < 0:
            self.entry_order = self.close()
            return
        if buy_open and (not self.position or self.position.size <= 0):
            if self.position and self.position.size < 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('buy')
            self.entry_order = self.buy(size=self.p.size)
            return
        if sell_open and (not self.position or self.position.size >= 0):
            if self.position and self.position.size > 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('sell')
            self.entry_order = self.sell(size=self.p.size)

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
                self.current_side = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
