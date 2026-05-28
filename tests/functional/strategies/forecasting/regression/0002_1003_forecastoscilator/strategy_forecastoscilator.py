from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader.feeds as btfeeds
from backtrader.indicator import Indicator
from backtrader.strategy import Strategy
from backtrader.utils.dateintern import num2date
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


def _price_value(data, shift, mode):
    key = str(mode).lower()
    open_ = float(data.open[-shift]) if shift else float(data.open[0])
    high = float(data.high[-shift]) if shift else float(data.high[0])
    low = float(data.low[-shift]) if shift else float(data.low[0])
    close = float(data.close[-shift]) if shift else float(data.close[0])
    if key in ('close', '1', 'price_close'):
        return close
    if key in ('open', '2', 'price_open'):
        return open_
    if key in ('high', '3', 'price_high'):
        return high
    if key in ('low', '4', 'price_low'):
        return low
    if key in ('median', '5', 'price_median'):
        return (high + low) / 2.0
    if key in ('typical', '6', 'price_typical'):
        return (high + low + close) / 3.0
    if key in ('weighted', '7', 'price_weighted'):
        return (high + low + close + close) / 4.0
    if key in ('simple', '8', 'price_simpl'):
        return (open_ + close) / 2.0
    if key in ('quarter', '9', 'price_quarter'):
        return (high + low + open_ + close) / 4.0
    if key in ('trendfollow0', '10', 'price_trendfollow0'):
        if close > open_:
            return high
        if close < open_:
            return low
        return close
    if key in ('trendfollow1', '11', 'price_trendfollow1'):
        if close > open_:
            return (high + close) / 2.0
        if close < open_:
            return (low + close) / 2.0
        return close
    return close


class ForecastOscilator(Indicator):
    lines = ('ind', 'signal', 'buy', 'sell')
    params = dict(length=15, t3=3, b=0.7, ipc='close')

    def __init__(self):
        self.addminperiod(int(self.p.length) + 5)
        self._e1 = 0.0
        self._e2 = 0.0
        self._e3 = 0.0
        self._e4 = 0.0
        self._e5 = 0.0
        self._e6 = 0.0
        self._initialized = False

    def next(self):
        length = max(int(self.p.length), 1)
        t3 = max(int(self.p.t3), 1)
        b = float(self.p.b)
        b2 = b * b
        b3 = b2 * b
        c1 = -b3
        c2 = 3 * (b2 + b3)
        c3 = -3 * (2 * b2 + b + b3)
        c4 = 1 + 3 * b + b3 + 3 * b2
        n = max(1 + 0.5 * (t3 - 1), 1.0)
        w1 = 2.0 / (n + 1.0)
        w2 = 1.0 - w1
        kx = 6.0 / (length * (length + 1.0))
        br = (length + 1.0) / 3.0

        if len(self.data) <= length + 2:
            price = _price_value(self.data, 0, self.p.ipc)
            self.l.ind[0] = 0.0
            self.l.signal[0] = 0.0
            self.l.buy[0] = float('nan')
            self.l.sell[0] = float('nan')
            if not self._initialized:
                self._e1 = self._e2 = self._e3 = self._e4 = self._e5 = self._e6 = price
                self._initialized = True
            return

        weighted_sum = 0.0
        for i in range(length, 0, -1):
            tmp = i - br
            weighted_sum += tmp * _price_value(self.data, length - i, self.p.ipc)
        wt = weighted_sum * kx
        price_now = _price_value(self.data, 0, self.p.ipc)
        forecastosc = ((price_now - wt) / wt * 100.0) if wt else 0.0

        if not self._initialized:
            self._e1 = self._e2 = self._e3 = self._e4 = self._e5 = self._e6 = forecastosc
            self._initialized = True

        self._e1 = w1 * forecastosc + w2 * self._e1
        self._e2 = w1 * self._e1 + w2 * self._e2
        self._e3 = w1 * self._e2 + w2 * self._e3
        self._e4 = w1 * self._e3 + w2 * self._e4
        self._e5 = w1 * self._e4 + w2 * self._e5
        self._e6 = w1 * self._e5 + w2 * self._e6
        t3_fosc = c1 * self._e6 + c2 * self._e5 + c3 * self._e4 + c4 * self._e3

        self.l.ind[0] = forecastosc
        self.l.signal[0] = t3_fosc
        self.l.buy[0] = float('nan')
        self.l.sell[0] = float('nan')

        if len(self.data) >= length + 4:
            ind_prev1 = float(self.l.ind[-1])
            ind_prev2 = float(self.l.ind[-2])
            sig_prev1 = float(self.l.signal[-1])
            sig_prev2 = float(self.l.signal[-2])
            sig_prev3 = float(self.l.signal[-3])
            if ind_prev1 > sig_prev2 and ind_prev2 <= sig_prev3 and sig_prev1 < 0:
                self.l.buy[0] = t3_fosc - 0.05
            if ind_prev1 < sig_prev2 and ind_prev2 >= sig_prev3 and sig_prev1 > 0:
                self.l.sell[0] = t3_fosc + 0.05


class ForecastOscilatorStrategy(Strategy):
    params = dict(
        signal_bar=1,
        length=15,
        t3=3,
        b=0.7,
        ipc='close',
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
    )

    def __init__(self):
        self.indicator = ForecastOscilator(self.data, length=self.p.length, t3=self.p.t3, b=self.p.b, ipc=self.p.ipc)
        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.pending_entry_direction = 0
        self.warmup = max(int(self.p.length) + max(int(self.p.signal_bar), 1) + 10, 40)

    def log(self, text):
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signal_value(self, line, shift):
        value = float(line[-shift]) if shift else float(line[0])
        return None if math.isnan(value) else value

    def _get_signals(self):
        shift = max(int(self.p.signal_bar), 1)
        up = self._signal_value(self.indicator.buy, shift)
        dn = self._signal_value(self.indicator.sell, shift)
        buy_open = self.p.buy_pos_open and up is not None
        sell_open = self.p.sell_pos_open and dn is not None
        buy_close = self.p.buy_pos_close and sell_open
        sell_close = self.p.sell_pos_close and buy_open
        return buy_open, sell_open, buy_close, sell_close

    def _reset_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None

    def _open_long(self):
        self.pending_entry_direction = 1
        self.buy(size=self.p.lot)

    def _open_short(self):
        self.pending_entry_direction = -1
        self.sell(size=self.p.lot)

    def _close_long(self, reason):
        self.log(reason)
        self.close()
        self._reset_levels()

    def _close_short(self, reason):
        self.log(reason)
        self.close()
        self._reset_levels()

    def _manage_protective_levels(self):
        if not self.position or self.entry_price is None:
            return False
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self._close_long(f'close long stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and high >= self.target_price:
                self._close_long(f'close long target={self.target_price:.2f}')
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self._close_short(f'close short stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and low <= self.target_price:
                self._close_short(f'close short target={self.target_price:.2f}')
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.warmup:
            return
        if self._manage_protective_levels():
            return

        buy_open, sell_open, buy_close, sell_close = self._get_signals()
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1

        if self.position:
            if self.position.size > 0:
                if buy_close:
                    self._close_long('close long on sell arrow')
                    if sell_open:
                        self._open_short()
                    return
            else:
                if sell_close:
                    self._close_short('close short on buy arrow')
                    if buy_open:
                        self._open_long()
                    return
        else:
            if buy_open:
                self.log('buy on forecast oscillator arrow')
                self._open_long()
                return
            if sell_open:
                self.log('sell on forecast oscillator arrow')
                self._open_short()
                return

    def notify_order(self, order):
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.pending_entry_direction = 0
            self.log(f'order {order.getstatusname()}')
            return
        if order.status != order.Completed:
            return
        self.completed_order_count += 1
        if self.pending_entry_direction == 1 and order.isbuy():
            self.buy_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return
        if self.pending_entry_direction == -1 and order.issell():
            self.sell_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return
        if not self.position:
            self._reset_levels()

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
