from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TimesDirectionStrategy(bt.Strategy):
    params = dict(
        open_time='13:00',
        close_time='18:00',
        trade_interval_minutes=60,
        trade_direction='sell',
        lots=0.1,
        stop_loss=1000,
        take_profit=2000,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self._position_was_open = False
        self.open_clock = self._parse_clock(self.p.open_time)
        self.close_clock = self._parse_clock(self.p.close_time)
        self.trade_interval = datetime.timedelta(minutes=int(self.p.trade_interval_minutes))
        self.last_open_day = None
        self.last_close_day = None
        self.stop_price = None
        self.take_profit_price = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _parse_clock(self, text):
        hour, minute = [int(part) for part in text.strip().split(':')]
        return datetime.time(hour=hour, minute=minute)

    def _within_first_interval(self, current_dt, target_clock, last_day):
        if current_dt.date() == last_day:
            return False
        start = datetime.datetime.combine(current_dt.date(), target_clock)
        end = start + self.trade_interval
        if not (start <= current_dt < end):
            return False
        if len(self.data) < 2:
            return True
        previous_dt = bt.num2date(self.data.datetime[-1])
        if previous_dt.date() != current_dt.date():
            return True
        return previous_dt < start <= current_dt

    def _set_risk_prices(self, is_long, price):
        if self.p.stop_loss:
            self.stop_price = round(price - self.p.stop_loss * self.p.point, self.p.price_digits) if is_long else round(price + self.p.stop_loss * self.p.point, self.p.price_digits)
        else:
            self.stop_price = None
        if self.p.take_profit:
            self.take_profit_price = round(price + self.p.take_profit * self.p.point, self.p.price_digits) if is_long else round(price - self.p.take_profit * self.p.point, self.p.price_digits)
        else:
            self.take_profit_price = None

    def _check_risk_exit(self):
        if not self.position:
            return False
        high_price = round(float(self.data.high[0]), self.p.price_digits)
        low_price = round(float(self.data.low[0]), self.p.price_digits)
        if self.position.size > 0:
            if self.stop_price is not None and low_price <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.2f}')
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and high_price >= self.take_profit_price:
                self.log(f'close long by take_profit={self.take_profit_price:.2f}')
                self.entry_order = self.close()
                return True
        else:
            if self.stop_price is not None and high_price >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.2f}')
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and low_price <= self.take_profit_price:
                self.log(f'close short by take_profit={self.take_profit_price:.2f}')
                self.entry_order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        dt = bt.num2date(self.data.datetime[0])

        if self.entry_order is not None:
            return

        if self.position:
            if self._check_risk_exit():
                return
            should_close = self._within_first_interval(dt, self.close_clock, self.last_close_day)
            if should_close:
                self.last_close_day = dt.date()
                self.log('close position by schedule')
                self.entry_order = self.close()
            return

        should_open = self._within_first_interval(dt, self.open_clock, self.last_open_day)
        if not should_open:
            return

        self.last_open_day = dt.date()
        close_price = round(float(self.data.close[0]), self.p.price_digits)
        direction = str(self.p.trade_direction).lower()
        if direction == 'buy':
            self.log('open buy by schedule')
            self._set_risk_prices(True, close_price)
            self.entry_order = self.buy(size=self.p.lots)
        else:
            self.log('open sell by schedule')
            self._set_risk_prices(False, close_price)
            self.entry_order = self.sell(size=self.p.lots)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.log(f'entry filled price={order.executed.price:.2f} size={order.executed.size:.2f}')
            else:
                self.log(f'position closed price={order.executed.price:.2f} size={order.executed.size:.2f}')
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
