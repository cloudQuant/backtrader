from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import backtrader.feeds as btfeeds
import numpy as np
import pandas as pd

RAD2DEGREE = 180.0 / math.pi


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


class MamaFeed(btfeeds.PandasData):
    lines = ('mama', 'fama')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('mama', 6), ('fama', 7),
    )


def build_resampled_frame(df, indicator_minutes):
    rule = f'{int(indicator_minutes)}min'
    signal_df = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    signal_df = signal_df.dropna(subset=['open', 'high', 'low', 'close']).copy()
    signal_df['openinterest'] = signal_df['openinterest'].fillna(0)
    return signal_df


def i_mama_series(price_series, fast_limit, slow_limit):
    prices = [float(v) for v in price_series]
    bars = len(prices)
    mama = [math.nan] * bars
    fama = [math.nan] * bars
    if bars == 0:
        return mama, fama

    work = [dict(
        price=0.0,
        smooth=0.0,
        detrender=0.0,
        q1=0.0,
        i1=0.0,
        ji=0.0,
        jq=0.0,
        i2=0.0,
        q2=0.0,
        re=0.0,
        im=0.0,
        period=0.0,
        phase=0.0,
        sa=0.0,
        mama=0.0,
        fama=0.0,
    ) for _ in range(bars)]

    def calc_comp(r, field):
        if r > 5:
            return (
                0.0962 * work[r][field]
                + 0.5769 * work[r - 2][field]
                - 0.5769 * work[r - 4][field]
                - 0.0962 * work[r - 6][field]
            ) * (0.075 * work[r - 1]['period'] + 0.54)
        return work[r][field]

    for r in range(bars):
        price = prices[r]
        work[r]['price'] = price
        if r > 3:
            work[r]['smooth'] = (4.0 * work[r]['price'] + 3.0 * work[r - 1]['price'] + 2.0 * work[r - 2]['price'] + work[r - 3]['price']) / 10.0
        else:
            work[r]['smooth'] = price

        work[r]['detrender'] = calc_comp(r, 'smooth')
        work[r]['q1'] = calc_comp(r, 'detrender')
        work[r]['i1'] = work[r - 3]['detrender'] if r > 2 else work[r]['detrender']
        work[r]['ji'] = calc_comp(r, 'i1')
        work[r]['jq'] = calc_comp(r, 'q1')

        if r == 0:
            work[r]['i2'] = work[r]['i1']
            work[r]['q2'] = work[r]['q1']
            work[r]['re'] = work[r]['i2']
            work[r]['im'] = work[r]['i2']
            current_period = 0.0
        else:
            work[r]['i2'] = 0.2 * (work[r]['i1'] - work[r]['jq']) + 0.8 * work[r - 1]['i2']
            work[r]['q2'] = 0.2 * (work[r]['q1'] + work[r]['ji']) + 0.8 * work[r - 1]['q2']
            work[r]['re'] = 0.2 * (work[r]['i2'] * work[r - 1]['i2'] + work[r]['q2'] * work[r - 1]['q2']) + 0.8 * work[r - 1]['re']
            work[r]['im'] = 0.2 * (work[r]['i2'] * work[r - 1]['q2'] - work[r]['q2'] * work[r - 1]['i2']) + 0.8 * work[r - 1]['im']
            current_period = work[r - 1]['period']

        if work[r]['re'] != 0 and work[r]['im'] != 0:
            current_period = 360.0 / (math.atan(work[r]['im'] / work[r]['re']) * RAD2DEGREE)
        if r > 0:
            current_period = min(current_period, 1.50 * work[r - 1]['period'])
            current_period = max(current_period, 0.67 * work[r - 1]['period'])
        current_period = min(max(current_period, 6.0), 50.0)
        if r > 0:
            current_period = 0.2 * current_period + 0.8 * work[r - 1]['period']
        work[r]['period'] = current_period

        if work[r]['i1'] != 0:
            work[r]['phase'] = math.atan(work[r]['q1'] / work[r]['i1']) * RAD2DEGREE
        else:
            work[r]['phase'] = RAD2DEGREE
        delta_phase = 0.0 if r == 0 else max(work[r - 1]['phase'] - work[r]['phase'], 1.0)
        alpha = max(min(fast_limit / delta_phase, fast_limit), slow_limit) if delta_phase != 0 else 1.0
        work[r]['sa'] = alpha

        if r == 0:
            work[r]['mama'] = price
            work[r]['fama'] = price
        else:
            work[r]['mama'] = work[r]['sa'] * work[r]['price'] + (1.0 - work[r]['sa']) * work[r - 1]['mama']
            work[r]['fama'] = 0.5 * work[r]['sa'] * work[r]['mama'] + (1.0 - 0.5 * work[r]['sa']) * work[r - 1]['fama']

        mama[r] = work[r]['mama']
        fama[r] = work[r]['fama']

    return mama, fama


def build_mama_frame(df, indicator_minutes, fast_limit, slow_limit):
    signal_df = build_resampled_frame(df, indicator_minutes)
    mama, fama = i_mama_series(signal_df['close'].astype(float).tolist(), float(fast_limit), float(slow_limit))
    signal_df = signal_df.copy()
    signal_df['mama'] = mama
    signal_df['fama'] = fama
    return signal_df


class MamaStrategy(bt.Strategy):
    params = dict(
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        mm=-0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
        fast_limit=0.5,
        slow_limit=0.05,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _line_value(self, line, ago):
        return float(line[-ago]) if ago else float(line[0])

    def _position_size(self, price):
        if self.p.mm < 0:
            return abs(float(self.p.mm))
        if price <= 0:
            return 0.0
        cash = self.broker.getcash()
        return round((cash * float(self.p.mm)) / price, 4)

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        point_value = float(self.p.point)
        stop_distance = self.p.stop_loss_points * point_value if self.p.stop_loss_points > 0 else None
        take_distance = self.p.take_profit_points * point_value if self.p.take_profit_points > 0 else None
        entry_price = float(self.position.price)

        if self.position.size > 0:
            if stop_distance is not None and close_price <= entry_price - stop_distance:
                self.log(f'close long by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price >= entry_price + take_distance:
                self.log(f'close long by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        elif self.position.size < 0:
            if stop_distance is not None and close_price >= entry_price + stop_distance:
                self.log(f'close short by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price <= entry_price - take_distance:
                self.log(f'close short by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 2:
            return

        if self._check_exit_levels():
            return

        signal_bar = max(int(self.p.signal_bar), 1)
        if len(self.signal) < signal_bar + 1:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        recent_ago = signal_bar - 1
        prev_ago = signal_bar
        mama_recent = self._line_value(self.signal.mama, recent_ago)
        fama_recent = self._line_value(self.signal.fama, recent_ago)
        mama_prev = self._line_value(self.signal.mama, prev_ago)
        fama_prev = self._line_value(self.signal.fama, prev_ago)
        if not all(math.isfinite(v) for v in [mama_recent, fama_recent, mama_prev, fama_prev]):
            return

        buy_signal = mama_recent > fama_recent and mama_prev < fama_prev
        sell_signal = mama_recent < fama_recent and mama_prev > fama_prev
        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} mama={mama_recent:.2f} fama={fama_recent:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} mama={mama_recent:.2f} fama={fama_recent:.2f}')
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
            if self.position.size >= 0 and self.p.sell_pos_open:
                self.sell(size=size)

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
