from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3] / 'backtrader'
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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


class F2aAOIndicator(bt.Indicator):
    lines = ('sell', 'buy')
    params = dict(ma_filtr=3, ma_fast=13, ma_slow=144)

    def __init__(self):
        series = (self.data.close * 5.0 + self.data.open * 2.0 + self.data.high + self.data.low) / 9.0
        self._fast = bt.indicators.ExponentialMovingAverage(series, period=max(1, int(self.p.ma_fast)))
        self._slow = bt.indicators.ExponentialMovingAverage(series, period=max(1, int(self.p.ma_slow)))
        self._filter = bt.indicators.ExponentialMovingAverage(series, period=max(1, int(self.p.ma_filtr)))
        self.addminperiod(max(int(self.p.ma_slow), int(self.p.ma_fast), int(self.p.ma_filtr)) + 20)
        self._trend = 0

    def next(self):
        value1_0 = float(self._fast[0]) - float(self._slow[0])
        value1_1 = float(self._fast[-1]) - float(self._slow[-1])
        value1_2 = float(self._fast[-2]) - float(self._slow[-2])
        current = float(self._filter[0])
        prev = float(self._filter[-1])
        avg_range = 0.0
        for count in range(10):
            avg_range += abs(float(self.data.high[-count]) - float(self.data.low[-count]))
        range_value = avg_range / 10.0
        self.lines.buy[0] = 0.0
        self.lines.sell[0] = 0.0
        if self._trend <= 0:
            if value1_0 > value1_1 and current >= prev and value1_1 <= value1_2:
                self.lines.buy[0] = float(self.data.low[0]) - range_value * 0.5
                self._trend = 1
        if self._trend >= 0:
            if value1_0 < value1_1 and current <= prev and value1_1 >= value1_2:
                self.lines.sell[0] = float(self.data.high[0]) + range_value * 0.5
                self._trend = -1

    def once(self, start, end):
        fast = self._fast.array
        slow = self._slow.array
        filtr = self._filter.array
        high = self.data.high.array
        low = self.data.low.array
        buy = self.lines.buy.array
        sell = self.lines.sell.array
        trend = 0
        for i in range(start, end):
            buy[i] = 0.0
            sell[i] = 0.0
            if i < 12:
                continue
            value1_0 = float(fast[i]) - float(slow[i])
            value1_1 = float(fast[i - 1]) - float(slow[i - 1])
            value1_2 = float(fast[i - 2]) - float(slow[i - 2])
            current = float(filtr[i])
            prev = float(filtr[i - 1])
            if not all(math.isfinite(v) for v in (value1_0, value1_1, value1_2, current, prev)):
                continue
            avg_range = 0.0
            valid_ranges = 0
            for count in range(10):
                idx = i - count
                bar_range = abs(float(high[idx]) - float(low[idx]))
                if math.isfinite(bar_range):
                    avg_range += bar_range
                    valid_ranges += 1
            range_value = avg_range / valid_ranges if valid_ranges else 0.0
            if trend <= 0 and value1_0 > value1_1 and current >= prev and value1_1 <= value1_2:
                buy[i] = float(low[i]) - range_value * 0.5
                trend = 1
            if trend >= 0 and value1_0 < value1_1 and current <= prev and value1_1 >= value1_2:
                sell[i] = float(high[i]) + range_value * 0.5
                trend = -1
        self._trend = trend


class F2aAOStrategy(bt.Strategy):
    params = dict(
        inp_timeframe='D1',
        trend_bar=1,
        ma_filtr=3,
        ma_fast=13,
        ma_slow=144,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = F2aAOIndicator(self.data, ma_filtr=self.p.ma_filtr, ma_fast=self.p.ma_fast, ma_slow=self.p.ma_slow)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _trend_value(self):
        idx = -max(1, int(self.p.trend_bar))
        return float(self.data.close[idx] - self.data.open[idx])

    def _has_recent_signal(self, line, shift, limit=120):
        start = max(shift + 1, 1)
        max_lookback = min(len(self.data) - 1, start + limit)
        for bar in range(start, max_lookback):
            if float(line[-bar]) != 0.0:
                return True
        return False

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        up_value = float(self.indicator.buy[-shift])
        dn_value = float(self.indicator.sell[-shift])
        trend = self._trend_value()
        buy_open = up_value != 0.0
        sell_open = dn_value != 0.0
        buy_close = sell_open
        sell_close = buy_open
        if not buy_close and not sell_close:
            if self.position.size < 0 and self._has_recent_signal(self.indicator.buy, shift):
                sell_close = True
            if self.position.size > 0 and self._has_recent_signal(self.indicator.sell, shift):
                buy_close = True
        if trend <= 0:
            buy_open = False
        if trend >= 0:
            sell_open = False
        return buy_open, sell_open, buy_close, sell_close, trend

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.ma_slow), int(self.p.ma_fast), int(self.p.ma_filtr)) + int(self.p.signal_bar) + int(self.p.trend_bar) + 20
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close, trend = self._signals()
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long trend={trend:.2f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell trend={trend:.2f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short trend={trend:.2f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy trend={trend:.2f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy trend={trend:.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell trend={trend:.2f}')
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
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
