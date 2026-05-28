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


class ClosePriceFractals(bt.Indicator):
    lines = ('upper', 'lower')

    def __init__(self):
        self.addminperiod(5)

    def next(self):
        self.lines.upper[0] = float('nan')
        self.lines.lower[0] = float('nan')
        candidate = float(self.data.close[-2])
        if candidate > float(self.data.close[-3]) and candidate > float(self.data.close[-4]) and candidate >= float(self.data.close[-1]) and candidate >= float(self.data.close[0]):
            self.lines.upper[0] = candidate
        if candidate < float(self.data.close[-3]) and candidate < float(self.data.close[-4]) and candidate <= float(self.data.close[-1]) and candidate <= float(self.data.close[0]):
            self.lines.lower[0] = candidate


class ClosePriceFractalsStrategy(bt.Strategy):
    params = dict(
        start_hour=10,
        end_hour=22,
        lots=0.1,
        stop_loss_pips=30,
        take_profit_pips=50,
        trailing_stop_pips=15,
        trailing_step_pips=5,
        point=0.01,
    )

    def __init__(self):
        self.fractals = ClosePriceFractals(self.data)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.stop_price = None
        self.take_profit_price = None
        self.trailing_anchor = None

    def _in_trade_window(self):
        dt = self.data.datetime.datetime(0)
        hour = dt.hour
        if self.p.start_hour < self.p.end_hour:
            return self.p.start_hour <= hour < self.p.end_hour
        if self.p.start_hour > self.p.end_hour:
            return not (hour < self.p.start_hour and hour >= self.p.end_hour)
        return True

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None
        self.trailing_anchor = None

    def _set_entry_risk(self, price, direction):
        sl = self.p.stop_loss_pips * self.p.point
        tp = self.p.take_profit_pips * self.p.point
        if direction > 0:
            self.stop_price = price - sl if self.p.stop_loss_pips > 0 else None
            self.take_profit_price = price + tp if self.p.take_profit_pips > 0 else None
        else:
            self.stop_price = price + sl if self.p.stop_loss_pips > 0 else None
            self.take_profit_price = price - tp if self.p.take_profit_pips > 0 else None
        self.trailing_anchor = price

    def _update_trailing(self):
        if not self.position or self.p.trailing_stop_pips <= 0:
            return False
        trail = self.p.trailing_stop_pips * self.p.point
        step = self.p.trailing_step_pips * self.p.point
        current = float(self.data.close[0])
        if self.position.size > 0:
            if current - self.position.price > trail + step:
                candidate = current - trail
                threshold = current - (trail + step)
                if self.stop_price is None or self.stop_price < threshold:
                    self.stop_price = candidate
        else:
            if self.position.price - current > trail + step:
                candidate = current + trail
                threshold = current + (trail + step)
                if self.stop_price is None or self.stop_price > threshold:
                    self.stop_price = candidate
        return False

    def _check_exit_levels(self):
        if not self.position:
            self._clear_risk()
            return False
        if self.position.size > 0:
            if self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and float(self.data.high[0]) >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and float(self.data.low[0]) <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def _last_two_fractals(self, line):
        values = []
        lookback = min(len(self.data) - 1, 30)
        for i in range(0, lookback):
            value = line[-i]
            if value == value:
                values.append(float(value))
            if len(values) >= 2:
                break
        if len(values) >= 2:
            return values[0], values[1]
        return None, None

    def next(self):
        self.bar_num += 1
        if len(self.data) < 8:
            return
        if self.order:
            return
        if not self._in_trade_window():
            if self.position:
                self.order = self.close()
            return
        if self._check_exit_levels():
            return
        self._update_trailing()

        last_lower, previous_lower = self._last_two_fractals(self.fractals.lower)
        last_upper, previous_upper = self._last_two_fractals(self.fractals.upper)

        if last_lower is not None and previous_lower is not None and previous_lower < last_lower:
            if self.position.size < 0:
                self.order = self.close()
                return
            if self.position.size == 0:
                self.order = self.buy(size=self.p.lots)
                return

        if last_upper is not None and previous_upper is not None and previous_upper > last_upper:
            if self.position.size > 0:
                self.order = self.close()
                return
            if self.position.size == 0:
                self.order = self.sell(size=self.p.lots)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and order.executed.size > 0:
                self.buy_count += 1
                if self.position.size > 0:
                    self._set_entry_risk(order.executed.price, 1)
            elif order.issell() and order.executed.size < 0:
                self.sell_count += 1
                if self.position.size < 0:
                    self._set_entry_risk(order.executed.price, -1)
            elif self.position.size == 0:
                self._clear_risk()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self._clear_risk()
