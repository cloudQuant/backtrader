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


class IndicesTesterStrategy(bt.Strategy):
    params = dict(
        comentar='Indices Tester',
        time_start='01:30',
        time_end='01:35',
        time_close='23:30',
        lots=0.10,
        limit_open_pos_sym=1,
        daily_num_positions=1,
        price_digits=2,
    )

    def __init__(self):
        self.entry_order = None
        self.bar_num = 0
        self.buy_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.closed_trades_by_day = {}
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _parse_hhmm(self, value):
        hour, minute = value.split(':')
        return int(hour), int(minute)

    def _is_within_window(self, dt, start, end):
        current = dt.hour * 60 + dt.minute
        start_val = start[0] * 60 + start[1]
        end_val = end[0] * 60 + end[1]
        return start_val < current < end_val

    def _is_after_close(self, dt, close_time):
        current = dt.hour * 60 + dt.minute
        close_val = close_time[0] * 60 + close_time[1]
        return current >= close_val

    def _closed_trades_today(self, dt):
        return self.closed_trades_by_day.get(dt.date(), 0)

    def _record_closed_trade(self, dt):
        self.closed_trades_by_day[dt.date()] = self._closed_trades_today(dt) + 1

    def next(self):
        self.bar_num += 1
        dt = bt.num2date(self.data.datetime[0])
        start = self._parse_hhmm(self.p.time_start)
        end = self._parse_hhmm(self.p.time_end)
        close_time = self._parse_hhmm(self.p.time_close)

        if self._is_after_close(dt, close_time) and self.position:
            self.close()
            self.log('forced close at configured close time')
            return

        if self.position or self.entry_order is not None:
            return

        if self._closed_trades_today(dt) >= self.p.daily_num_positions:
            return

        if self.p.limit_open_pos_sym <= 0:
            return

        if self._is_within_window(dt, start, end):
            self.entry_order = self.buy(size=self.p.lots)
            self.log(f'buy signal in time window close={self.data.close[0]:.2f}')

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order is self.entry_order:
            if order.status == order.Completed:
                self.log(f'buy order filled price={order.executed.price:.2f}')
                self.entry_order = None
            else:
                self.entry_order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
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
        self._record_closed_trade(bt.num2date(self.data.datetime[0]))
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
