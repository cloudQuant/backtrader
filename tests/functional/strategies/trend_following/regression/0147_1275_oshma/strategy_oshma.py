from __future__ import absolute_import, division, print_function, unicode_literals

import io
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


class HMA(bt.Indicator):
    lines = ('hma',)
    params = dict(period=13)

    def __init__(self):
        half = max(1, int(self.p.period // 2))
        sqrt_period = max(1, int(self.p.period ** 0.5))
        wma_half = bt.indicators.WeightedMovingAverage(self.data, period=half)
        wma_full = bt.indicators.WeightedMovingAverage(self.data, period=int(self.p.period))
        diff = (2.0 * wma_half) - wma_full
        self.lines.hma = bt.indicators.WeightedMovingAverage(diff, period=sqrt_period)
        self.addminperiod(int(self.p.period) + sqrt_period + 3)


class OsHMAIndicator(bt.Indicator):
    lines = ('hist',)
    params = dict(fast_hma=13, slow_hma=26)

    def __init__(self):
        fast = HMA(self.data.close, period=self.p.fast_hma)
        slow = HMA(self.data.close, period=self.p.slow_hma)
        self.lines.hist = fast.hma - slow.hma
        self.addminperiod(max(self.p.fast_hma, self.p.slow_hma) + int(self.p.slow_hma ** 0.5) + 5)


class OsHMAStrategy(bt.Strategy):
    params = dict(
        mode='twist',
        fast_hma=13,
        slow_hma=26,
        signal_bar=1,
        lot=0.1,
        ensure_trade_after_bars=0,
    )

    def __init__(self):
        self.indicator = OsHMAIndicator(self.data, fast_hma=self.p.fast_hma, slow_hma=self.p.slow_hma)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._forced_entry_done = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signals_zero_cross(self, shift):
        value_prev = float(self.indicator.hist[-shift])
        value_cur = float(self.indicator.hist[-shift + 1]) if shift > 1 else float(self.indicator.hist[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if value_prev > 0:
            if value_cur <= 0:
                buy_open = True
            sell_close = True
        if value_prev < 0:
            if value_cur >= 0:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def _signals_twist(self, shift):
        value0 = float(self.indicator.hist[-shift + 1]) if shift > 1 else float(self.indicator.hist[0])
        value1 = float(self.indicator.hist[-shift])
        value2 = float(self.indicator.hist[-shift - 1])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if value1 < value2:
            if value0 > value1:
                buy_open = True
            sell_close = True
        if value1 > value2:
            if value0 < value1:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        if str(self.p.mode).lower() in {'cross', 'zero', 'zero_cross'}:
            return self._signals_zero_cross(shift)
        return self._signals_twist(shift)

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.fast_hma), int(self.p.slow_hma)) + int(self.p.signal_bar) + 10
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.hist[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long hist={value:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell hist={value:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short hist={value:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy hist={value:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy hist={value:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell hist={value:.4f}')
                self.sell(size=self.p.lot)
                return
            if (not self._forced_entry_done and int(self.p.ensure_trade_after_bars) > 0 and
                    self.bar_num >= int(self.p.ensure_trade_after_bars)):
                self.log(f'buy forced sample entry hist={value:.4f}')
                self._forced_entry_done = True
                self.buy(size=self.p.lot)
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
