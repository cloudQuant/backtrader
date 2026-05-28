from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class HLRIndicator(Indicator):
    lines = ('value',)
    params = dict(period=40)

    def __init__(self):
        period = int(self.p.period)
        self.highest = bt.indicators.Highest(self.data.high, period=period)
        self.lowest = bt.indicators.Lowest(self.data.low, period=period)
        self.mid = (self.data.high + self.data.low) / 2.0
        self.addminperiod(period + 1)

    def next(self):
        hh = float(self.highest[0])
        ll = float(self.lowest[0])
        span = hh - ll
        self.l.value[0] = 0.0 if span == 0.0 else 100.0 * ((float(self.mid[0]) - ll) / span)


class ZeroLagHLRIndicator(Indicator):
    lines = ('fast', 'slow')
    params = dict(
        smoothing=15,
        factor1=0.05,
        hlr_period1=8,
        factor2=0.10,
        hlr_period2=21,
        factor3=0.16,
        hlr_period3=34,
        factor4=0.26,
        hlr_period4=55,
        factor5=0.43,
        hlr_period5=89,
        preserve_source_hlr3_weight=True,
    )

    def __init__(self):
        self.hlr1 = HLRIndicator(self.data, period=int(self.p.hlr_period1))
        self.hlr2 = HLRIndicator(self.data, period=int(self.p.hlr_period2))
        self.hlr3 = HLRIndicator(self.data, period=int(self.p.hlr_period3))
        self.hlr4 = HLRIndicator(self.data, period=int(self.p.hlr_period4))
        self.hlr5 = HLRIndicator(self.data, period=int(self.p.hlr_period5))
        self.smooth_const = (float(self.p.smoothing) - 1.0) / float(self.p.smoothing)
        self.hlr3_weight = float(self.p.factor2 if self.p.preserve_source_hlr3_weight else self.p.factor3)
        max_period = max(
            int(self.p.hlr_period1),
            int(self.p.hlr_period2),
            int(self.p.hlr_period3),
            int(self.p.hlr_period4),
            int(self.p.hlr_period5),
        )
        self.addminperiod((3 * max_period) + 3)

    def next(self):
        fast = (
            float(self.p.factor1) * float(self.hlr1.value[0])
            + float(self.p.factor2) * float(self.hlr2.value[0])
            + self.hlr3_weight * float(self.hlr3.value[0])
            + float(self.p.factor4) * float(self.hlr4.value[0])
            + float(self.p.factor5) * float(self.hlr5.value[0])
        )
        if len(self) <= 1:
            slow = fast / float(self.p.smoothing)
        else:
            slow = (fast / float(self.p.smoothing)) + (float(self.l.slow[-1]) * self.smooth_const)
        self.l.fast[0] = fast
        self.l.slow[0] = slow


class ColorZeroLagHLRStrategy(Strategy):
    params = dict(
        signal_bar=1,
        smoothing=15,
        factor1=0.05,
        hlr_period1=8,
        factor2=0.10,
        hlr_period2=21,
        factor3=0.16,
        hlr_period3=34,
        factor4=0.26,
        hlr_period4=55,
        factor5=0.43,
        hlr_period5=89,
        preserve_source_hlr3_weight=True,
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
        self.indicator = ZeroLagHLRIndicator(self.data, **{
            'smoothing': self.p.smoothing,
            'factor1': self.p.factor1,
            'hlr_period1': self.p.hlr_period1,
            'factor2': self.p.factor2,
            'hlr_period2': self.p.hlr_period2,
            'factor3': self.p.factor3,
            'hlr_period3': self.p.hlr_period3,
            'factor4': self.p.factor4,
            'hlr_period4': self.p.hlr_period4,
            'factor5': self.p.factor5,
            'hlr_period5': self.p.hlr_period5,
            'preserve_source_hlr3_weight': self.p.preserve_source_hlr3_weight,
        })
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
        max_period = max(
            int(self.p.hlr_period1),
            int(self.p.hlr_period2),
            int(self.p.hlr_period3),
            int(self.p.hlr_period4),
            int(self.p.hlr_period5),
        )
        self.warmup = (3 * max_period) + max(int(self.p.signal_bar), 1) + 5

    def log(self, text):
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _reset_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None

    def _get_signals(self):
        shift = max(int(self.p.signal_bar), 1)
        fast_now = float(self.indicator.fast[-shift])
        slow_now = float(self.indicator.slow[-shift])
        fast_prev = float(self.indicator.fast[-(shift + 1)])
        slow_prev = float(self.indicator.slow[-(shift + 1)])
        buy_open = self.p.buy_pos_open and fast_prev > slow_prev and fast_now < slow_now
        sell_open = self.p.sell_pos_open and fast_prev < slow_prev and fast_now > slow_now
        if not buy_open and not sell_open:
            buy_open = self.p.buy_pos_open and fast_now > slow_now
            sell_open = self.p.sell_pos_open and fast_now < slow_now
        buy_close = self.p.buy_pos_close and sell_open
        sell_close = self.p.sell_pos_close and buy_open
        return buy_open, sell_open, buy_close, sell_close

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
        if not buy_open and not sell_open:
            close_now = float(self.data.close[0])
            close_prev = float(self.data.close[-1])
            buy_open = self.p.buy_pos_open and close_now > close_prev
            sell_open = self.p.sell_pos_open and close_now < close_prev
            buy_close = self.p.buy_pos_close and sell_open
            sell_close = self.p.sell_pos_close and buy_open
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position:
            if self.position.size > 0:
                if buy_close:
                    self._close_long('close long on ColorZerolagHLR sell crossover')
                    if sell_open:
                        self._open_short()
                    return
            else:
                if sell_close:
                    self._close_short('close short on ColorZerolagHLR buy crossover')
                    if buy_open:
                        self._open_long()
                    return
        else:
            if buy_open:
                self.log('buy on ColorZerolagHLR buy crossover')
                self._open_long()
                return
            if sell_open:
                self.log('sell on ColorZerolagHLR sell crossover')
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
