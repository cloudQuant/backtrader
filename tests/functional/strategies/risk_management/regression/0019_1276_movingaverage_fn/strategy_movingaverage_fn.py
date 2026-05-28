from __future__ import absolute_import, division, print_function, unicode_literals

import io
import re
import sys
from collections import deque
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3] / 'backtrader'
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import backtrader as bt
import pandas as pd

SOURCE_MQ5 = Path(__file__).resolve().parents[2] / 'ea' / '1276_Exp_MovingAverage_FN' / 'movingaverage_fn.mq5'


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


def resolve_ma_class(name):
    mode = str(name).lower()
    if mode in {'sma', 'mode_sma'}:
        return bt.indicators.SMA
    if mode in {'ema', 'mode_ema'}:
        return bt.indicators.EMA
    if mode in {'smma', 'mode_smma'}:
        return bt.indicators.SmoothedMovingAverage
    return bt.indicators.WeightedMovingAverage


def resolve_price_line(data, mode):
    price_mode = str(mode).lower()
    if price_mode in {'price_open', 'open'}:
        return data.open
    if price_mode in {'price_high', 'high'}:
        return data.high
    if price_mode in {'price_low', 'low'}:
        return data.low
    if price_mode in {'price_median', 'median'}:
        return (data.high + data.low) / 2.0
    if price_mode in {'price_typical', 'typical'}:
        return (data.high + data.low + data.close) / 3.0
    if price_mode in {'price_weighted', 'weighted'}:
        return (data.high + data.low + data.close + data.close) / 4.0
    return data.close


@lru_cache(maxsize=None)
def load_fn_coefficients(filter_name='N44'):
    if not SOURCE_MQ5.exists():
        return [1.0]
    raw = SOURCE_MQ5.read_bytes()
    candidates = []
    for encoding in ('utf-16', 'utf-16-le', 'utf-8', 'latin-1'):
        try:
            candidates.append(raw.decode(encoding, errors='ignore'))
        except Exception:
            continue
    text = ''
    for candidate in candidates:
        normalized = candidate.replace('\x00', '')
        if f'case {filter_name}:' in normalized:
            text = normalized
            break
    if not text:
        text = raw.decode('latin-1', errors='ignore').replace('\x00', '')
    start = text.find(f'case {filter_name}:')
    if start == -1:
        raise ValueError(f'Filter {filter_name} not found in {SOURCE_MQ5}')
    next_case = re.search(r'\n\s*case\s+N\d+:', text[start + 1:])
    if not next_case:
        raise ValueError(f'Could not locate next filter after {filter_name}')
    block = text[start:start + 1 + next_case.start()]
    matches = re.findall(r'([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\*PriceSeries\(Price,index(?:-(\d+))?', block)
    coeff_map = {int(offset or '0'): float(coef) for coef, offset in matches}
    coeffs = [coeff_map[i] for i in range(max(coeff_map) + 1)]
    return coeffs


class MovingAverageFNIndicator(bt.Indicator):
    lines = ('mafn',)
    params = dict(
        filter_number='N44',
        xma_method='jjma',
        xlength=12,
        xphase=15,
        ipc='price_close',
        price_shift=0,
    )

    def __init__(self):
        self._coeffs = load_fn_coefficients(self.p.filter_number)
        self._price_line = resolve_price_line(self.data, self.p.ipc)
        self._smooth_values = deque(maxlen=max(1, int(self.p.xlength)))
        self.addminperiod(len(self._coeffs) + self.p.xlength + 5)

    def _smooth_filtered(self, value):
        self._smooth_values.append(value)
        values = list(self._smooth_values)
        if not values:
            return value
        mode = str(self.p.xma_method).lower()
        if mode in {'sma', 'mode_sma'}:
            return sum(values) / len(values)
        if mode in {'ema', 'mode_ema'}:
            alpha = 2.0 / (len(values) + 1.0)
            ema = values[0]
            for item in values[1:]:
                ema = alpha * item + (1.0 - alpha) * ema
            return ema
        weights = list(range(1, len(values) + 1))
        weight_sum = float(sum(weights))
        return sum(v * w for v, w in zip(values, weights)) / weight_sum

    def next(self):
        filtered = 0.0
        for offset, coef in enumerate(self._coeffs):
            filtered += coef * float(self._price_line[-offset])
        self.lines.mafn[0] = self._smooth_filtered(filtered) + float(self.p.price_shift)


class MovingAverageFNStrategy(bt.Strategy):
    params = dict(
        filter_number='N44',
        xma_method='jjma',
        xlength=12,
        xphase=15,
        ipc='price_close',
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        self.indicator = MovingAverageFNIndicator(
            self.data,
            filter_number=self.p.filter_number,
            xma_method=self.p.xma_method,
            xlength=self.p.xlength,
            xphase=self.p.xphase,
            ipc=self.p.ipc,
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

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        value0 = float(self.indicator.mafn[-shift + 1]) if shift > 1 else float(self.indicator.mafn[0])
        value1 = float(self.indicator.mafn[-shift])
        value2 = float(self.indicator.mafn[-shift - 1])
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

    def next(self):
        self.bar_num += 1
        warmup = len(load_fn_coefficients(self.p.filter_number)) + int(self.p.xlength) + int(self.p.signal_bar) + 5
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.mafn[0])
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
