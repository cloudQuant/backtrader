from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from collections import deque
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


class TwoPbIdealXOSMAIndicator(bt.Indicator):
    lines = ('signal',)
    params = dict(
        period1=10,
        period2=10,
        periodx1=10,
        periodx2=10,
        periody1=10,
        periody2=10,
        periodz1=10,
        periodz2=10,
        smooth_method='jjma',
        smooth_period=9,
        smooth_phase=100,
    )

    def __init__(self):
        self._w1 = 1.0 / max(1, int(self.p.period1))
        self._w2 = 1.0 / max(1, int(self.p.period2))
        self._wx1 = 1.0 / max(1, int(self.p.periodx1))
        self._wx2 = 1.0 / max(1, int(self.p.periodx2))
        self._wy1 = 1.0 / max(1, int(self.p.periody1))
        self._wy2 = 1.0 / max(1, int(self.p.periody2))
        self._wz1 = 1.0 / max(1, int(self.p.periodz1))
        self._wz2 = 1.0 / max(1, int(self.p.periodz2))
        self._fast_state = None
        self._moving01 = None
        self._moving11 = None
        self._moving21 = None
        self._smooth_state = None
        self._smooth_values = deque(maxlen=max(1, int(self.p.smooth_period)))
        self.addminperiod(
            max(
                int(self.p.period1),
                int(self.p.period2),
                int(self.p.periodx1),
                int(self.p.periodx2),
                int(self.p.periody1),
                int(self.p.periody2),
                int(self.p.periodz1),
                int(self.p.periodz2),
                int(self.p.smooth_period),
            ) + 5
        )

    @staticmethod
    def _ideal_ma_smooth(weight_1, weight_2, series_1, series_0, result_1):
        dseries = series_0 - series_1
        dseries2 = dseries * dseries - 1.0
        denominator = 1.0 + weight_2 * dseries2
        if denominator == 0:
            return result_1
        return (
            weight_1 * (series_0 - result_1)
            + result_1
            + weight_2 * result_1 * dseries2
        ) / denominator

    def _smooth_histogram(self, value):
        method = str(self.p.smooth_method).lower()
        period = max(1, int(self.p.smooth_period))
        if method == 'sma':
            self._smooth_values.append(value)
            return sum(self._smooth_values) / len(self._smooth_values)
        if method == 'lwma':
            self._smooth_values.append(value)
            values = list(self._smooth_values)
            weights = list(range(1, len(values) + 1))
            return sum(v * w for v, w in zip(values, weights)) / sum(weights)
        if method == 'smma':
            if self._smooth_state is None:
                self._smooth_state = value
            else:
                self._smooth_state = ((period - 1) * self._smooth_state + value) / period
            return self._smooth_state
        alpha = 2.0 / (period + 1.0)
        if self._smooth_state is None:
            self._smooth_state = value
        else:
            self._smooth_state = self._smooth_state + alpha * (value - self._smooth_state)
        return self._smooth_state

    def next(self):
        price = float(self.data.close[0])
        prev_price = float(self.data.close[-1]) if len(self.data) > 1 else price
        if self._fast_state is None:
            self._fast_state = price
            self._moving01 = price
            self._moving11 = price
            self._moving21 = price

        self._fast_state = self._ideal_ma_smooth(self._w1, self._w2, prev_price, price, self._fast_state)
        moving00 = self._ideal_ma_smooth(self._wx1, self._wx2, prev_price, price, self._moving01)
        moving10 = self._ideal_ma_smooth(self._wy1, self._wy2, self._moving01, moving00, self._moving11)
        moving20 = self._ideal_ma_smooth(self._wz1, self._wz2, self._moving11, moving10, self._moving21)

        self._moving01 = moving00
        self._moving11 = moving10
        self._moving21 = moving20

        raw_macd = self._fast_state - moving20
        self.lines.signal[0] = self._smooth_histogram(raw_macd)


class TwoPbIdealXOSMAStrategy(bt.Strategy):
    params = dict(
        signal_bar=1,
        period1=10,
        period2=10,
        periodx1=10,
        periodx2=10,
        periody1=10,
        periody2=10,
        periodz1=10,
        periodz2=10,
        smooth_method='jjma',
        smooth_period=9,
        smooth_phase=100,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.signal = TwoPbIdealXOSMAIndicator(
            self.data,
            period1=self.p.period1,
            period2=self.p.period2,
            periodx1=self.p.periodx1,
            periodx2=self.p.periodx2,
            periody1=self.p.periody1,
            periody2=self.p.periody2,
            periodz1=self.p.periodz1,
            periodz2=self.p.periodz2,
            smooth_method=self.p.smooth_method,
            smooth_period=self.p.smooth_period,
            smooth_phase=self.p.smooth_phase,
        )
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

    def _turning_values(self):
        offset = max(1, int(self.p.signal_bar))
        return (
            float(self.signal.signal[-offset - 2]),
            float(self.signal.signal[-offset - 1]),
            float(self.signal.signal[-offset]),
        )

    def next(self):
        self.bar_num += 1
        min_bars = max(
            int(self.p.period1),
            int(self.p.period2),
            int(self.p.periodx1),
            int(self.p.periodx2),
            int(self.p.periody1),
            int(self.p.periody2),
            int(self.p.periodz1),
            int(self.p.periodz2),
            int(self.p.smooth_period),
        ) + int(self.p.signal_bar) + 5
        if len(self.data) < min_bars:
            return

        left_value, middle_value, right_value = self._turning_values()
        buy_signal = middle_value < left_value and right_value > middle_value
        sell_signal = middle_value > left_value and right_value < middle_value

        if self.position:
            if self.position.size > 0 and sell_signal:
                self.log(f'close long & sell signal={middle_value:.4f} latest={right_value:.4f}')
                self.close()
                self.sell(size=self.p.lot)
                return
            if self.position.size < 0 and buy_signal:
                self.log(f'close short & buy signal={middle_value:.4f} latest={right_value:.4f}')
                self.close()
                self.buy(size=self.p.lot)
                return
        else:
            if buy_signal:
                self.log(f'buy signal={middle_value:.4f} latest={right_value:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_signal:
                self.log(f'sell signal={middle_value:.4f} latest={right_value:.4f}')
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
