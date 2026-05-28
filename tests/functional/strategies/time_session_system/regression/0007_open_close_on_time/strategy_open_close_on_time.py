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


class OpenCloseOnTimeStrategy(bt.Strategy):
    params = dict(
        open_time='13:00',
        close_time='13:01',
        lots=1.0,
        buy=True,
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
        self.last_open_day = None
        self.last_close_day = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _parse_clock(self, text):
        hour, minute = [int(part) for part in text.strip().split(':')]
        return datetime.time(hour=hour, minute=minute)

    def _is_first_bar_after(self, current_dt, target_clock, last_day):
        if current_dt.date() == last_day:
            return False
        current_clock = current_dt.time().replace(second=0, microsecond=0)
        if current_clock < target_clock:
            return False
        if len(self.data) < 2:
            return True
        previous_dt = bt.num2date(self.data.datetime[-1])
        previous_clock = previous_dt.time().replace(second=0, microsecond=0)
        if previous_dt.date() != current_dt.date():
            return True
        return previous_clock < target_clock <= current_clock

    def next(self):
        self.bar_num += 1
        dt = bt.num2date(self.data.datetime[0])

        if self.entry_order is not None:
            return

        if self.position:
            should_close = self._is_first_bar_after(dt, self.close_clock, self.last_close_day)
            if should_close:
                self.last_close_day = dt.date()
                self.log('close position by schedule')
                self.entry_order = self.close()
            return

        should_open = self._is_first_bar_after(dt, self.open_clock, self.last_open_day)
        if not should_open:
            return

        self.last_open_day = dt.date()
        if self.p.buy:
            self.log('open buy by schedule')
            self.entry_order = self.buy(size=self.p.lots)
        else:
            self.log('open sell by schedule')
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
