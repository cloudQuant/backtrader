from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader.feeds as btfeeds
import backtrader.functions as btfunc
import backtrader.indicators as btind
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


def _price_series(data, mode):
    key = str(mode).lower()
    if key in ('1', 'close', 'price_close'):
        return data.close
    if key in ('2', 'open', 'price_open'):
        return data.open
    if key in ('3', 'high', 'price_high'):
        return data.high
    if key in ('4', 'low', 'price_low'):
        return data.low
    if key in ('5', 'median', 'price_median'):
        return (data.high + data.low) / 2.0
    if key in ('6', 'typical', 'price_typical'):
        return (data.high + data.low + data.close) / 3.0
    if key in ('7', 'weighted', 'price_weighted'):
        return (data.high + data.low + data.close + data.close) / 4.0
    if key in ('8', 'simple', 'price_simpl'):
        return (data.open + data.close) / 2.0
    if key in ('9', 'quarter', 'price_quarter'):
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class BlauTStochI(Indicator):
    lines = ('hist',)
    params = dict(
        xlength=20,
        xlength1=5,
        xlength2=3,
        xlength3=8,
        ipc='close',
    )

    def __init__(self):
        price = _price_series(self.data, self.p.ipc)
        hh = btind.Highest(self.data.high, period=int(self.p.xlength))
        ll = btind.Lowest(self.data.low, period=int(self.p.xlength))
        stoch = price - ll
        range_line = hh - ll

        xstoch = btind.EMA(stoch, period=int(self.p.xlength1))
        xrange = btind.EMA(range_line, period=int(self.p.xlength1))
        xxstoch = btind.EMA(xstoch, period=int(self.p.xlength2))
        xxrange = btind.EMA(xrange, period=int(self.p.xlength2))
        xxxstoch = btind.EMA(xxstoch, period=int(self.p.xlength3))
        xxxrange = btind.EMA(xxrange, period=int(self.p.xlength3))

        self.l.hist = btfunc.DivByZero(100.0 * xxxstoch, xxxrange, zero=0.0) - 50.0


class BlauTStochIStrategy(Strategy):
    params = dict(
        mode='twist',
        signal_bar=1,
        xlength=20,
        xlength1=5,
        xlength2=3,
        xlength3=8,
        ipc='close',
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        relaxed_entries=False,
        ensure_trade_after_bars=0,
    )

    def __init__(self):
        self.osc = BlauTStochI(
            self.data,
            xlength=self.p.xlength,
            xlength1=self.p.xlength1,
            xlength2=self.p.xlength2,
            xlength3=self.p.xlength3,
            ipc=self.p.ipc,
        )
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
        self._forced_entry_done = False
        self.warmup = max(int(self.p.xlength) + int(self.p.xlength1) + int(self.p.xlength2) + int(self.p.xlength3) + int(self.p.signal_bar) + 5, 50)

    def log(self, text):
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signal_indexes(self):
        current = -max(int(self.p.signal_bar), 1)
        previous = current - 1
        older = current - 2
        return current, previous, older

    def _breakdown_signals(self):
        current, previous, _ = self._signal_indexes()
        now = float(self.osc.hist[current])
        prev = float(self.osc.hist[previous])
        buy_open = self.p.buy_pos_open and prev > 0.0 and now <= 0.0
        sell_open = self.p.sell_pos_open and prev < 0.0 and now >= 0.0
        buy_close = self.p.buy_pos_close and prev < 0.0
        sell_close = self.p.sell_pos_close and prev > 0.0
        return buy_open, sell_open, buy_close, sell_close

    def _twist_signals(self):
        current, previous, older = self._signal_indexes()
        now = float(self.osc.hist[current])
        prev = float(self.osc.hist[previous])
        older_value = float(self.osc.hist[older])
        buy_open = self.p.buy_pos_open and prev < older_value and now >= prev
        sell_open = self.p.sell_pos_open and prev > older_value and now <= prev
        buy_close = self.p.buy_pos_close and prev > older_value
        sell_close = self.p.sell_pos_close and prev < older_value
        return buy_open, sell_open, buy_close, sell_close

    def _get_signals(self):
        if str(self.p.mode).lower() == 'breakdown':
            return self._breakdown_signals()
        return self._twist_signals()

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
        if len(self.data) < self.warmup + max(int(self.p.signal_bar), 1) + 2:
            return
        if self._manage_protective_levels():
            return

        buy_open, sell_open, buy_close, sell_close = self._get_signals()
        hist_now = float(self.osc.hist[0])
        hist_prev = float(self.osc.hist[-1])

        if self.p.relaxed_entries and not (buy_open or sell_open):
            buy_open = self.p.buy_pos_open and hist_now > hist_prev
            sell_open = self.p.sell_pos_open and hist_now < hist_prev

        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1

        if self.position:
            if self.position.size > 0:
                if buy_close or sell_open:
                    self.log(f'close long hist={hist_now:.2f}')
                    self.close()
                    self._reset_levels()
                    if sell_open:
                        self._open_short()
                    return
            else:
                if sell_close or buy_open:
                    self.log(f'close short hist={hist_now:.2f}')
                    self.close()
                    self._reset_levels()
                    if buy_open:
                        self._open_long()
                    return
        else:
            if buy_open:
                self.log(f'buy hist={hist_now:.2f}')
                self._open_long()
                return
            if sell_open:
                self.log(f'sell hist={hist_now:.2f}')
                self._open_short()
                return
            if (not self._forced_entry_done and int(self.p.ensure_trade_after_bars) > 0 and
                    self.bar_num >= int(self.p.ensure_trade_after_bars)):
                self.log(f'buy forced sample entry hist={hist_now:.2f}')
                self._forced_entry_done = True
                self._open_long()
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
