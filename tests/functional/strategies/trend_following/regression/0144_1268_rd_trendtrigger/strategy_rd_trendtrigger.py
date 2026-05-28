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


class RDTrendTriggerIndicator(bt.Indicator):
    lines = ('value',)
    params = dict(regress=15, t3_length=5, t3_phase=70)

    def __init__(self):
        self._ema = bt.indicators.ExponentialMovingAverage(self.lines.value, period=max(1, int(self.p.t3_length)))
        self.addminperiod(int(self.p.regress) * 2 + int(self.p.t3_length) + 3)

    def next(self):
        regress = int(self.p.regress)
        highs_recent = [float(self.data.high[-i]) for i in range(regress)]
        highs_older = [float(self.data.high[-regress - i]) for i in range(regress)]
        lows_recent = [float(self.data.low[-i]) for i in range(regress)]
        lows_older = [float(self.data.low[-regress - i]) for i in range(regress)]
        highest_high_recent = max(highs_recent)
        highest_high_older = max(highs_older)
        lowest_low_recent = min(lows_recent)
        lowest_low_older = min(lows_older)
        buy_power = highest_high_recent - lowest_low_older
        sell_power = highest_high_older - lowest_low_recent
        denom = buy_power + sell_power
        ttf = ((buy_power - sell_power) / (0.5 * denom) * 100.0) if denom else 0.0
        prev = float(self.lines.value[-1]) if len(self) > 0 else ttf
        period = max(1, int(self.p.t3_length))
        alpha = 2.0 / (period + 1.0)
        self.lines.value[0] = alpha * ttf + (1.0 - alpha) * prev


class RDTrendTriggerStrategy(bt.Strategy):
    params = dict(
        mode='twist',
        regress=15,
        t3_length=5,
        t3_phase=70,
        high_level=50,
        low_level=-50,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        basis = self.data.close - bt.indicators.SimpleMovingAverage(self.data.close, period=max(2, int(self.p.regress)))
        self.indicator = type('RDTrendTriggerLines', (), {})()
        self.indicator.value = bt.indicators.ExponentialMovingAverage(basis, period=max(1, int(self.p.t3_length)))
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

    def _signals_twist(self, shift):
        value0 = float(self.indicator.value[-shift + 1]) if shift > 1 else float(self.indicator.value[0])
        value1 = float(self.indicator.value[-shift])
        value2 = float(self.indicator.value[-shift - 1])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if value2 > value1:
            if value1 <= value0:
                buy_open = True
            sell_close = True
        if value2 < value1:
            if value1 >= value0:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def _signals_disposition(self, shift):
        value_prev = float(self.indicator.value[-shift])
        value_cur = float(self.indicator.value[-shift + 1]) if shift > 1 else float(self.indicator.value[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if value_prev > float(self.p.high_level):
            if value_cur <= float(self.p.high_level):
                buy_open = True
        if value_prev < float(self.p.low_level):
            if value_cur >= float(self.p.low_level):
                sell_open = True
        if value_prev > float(self.p.low_level):
            sell_close = True
        return buy_open, sell_open, buy_close, sell_close

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        if str(self.p.mode).lower() == 'disposition':
            return self._signals_disposition(shift)
        return self._signals_twist(shift)

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.regress) * 2 + int(self.p.t3_length) + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.value[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long value={value:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell value={value:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short value={value:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy value={value:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy value={value:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell value={value:.4f}')
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
