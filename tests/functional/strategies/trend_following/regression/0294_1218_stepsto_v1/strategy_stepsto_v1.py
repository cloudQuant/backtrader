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


class StepStoFeed(btfeeds.PandasData):
    lines = ('fast', 'slow', 'atr')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('fast', 6), ('slow', 7), ('atr', 8),
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


def atr_wilder(high_series, low_series, close_series, period):
    period = int(period)
    high = pd.Series(high_series, dtype=float).reset_index(drop=True)
    low = pd.Series(low_series, dtype=float).reset_index(drop=True)
    close = pd.Series(close_series, dtype=float).reset_index(drop=True)
    n = len(close)
    tr = [math.nan] * n
    atr = [math.nan] * n
    for idx in range(1, n):
        tr[idx] = max(
            high.iloc[idx] - low.iloc[idx],
            abs(high.iloc[idx] - close.iloc[idx - 1]),
            abs(low.iloc[idx] - close.iloc[idx - 1]),
        )
    if n <= period:
        return pd.Series(atr, dtype=float)
    seed = sum(v for v in tr[1:period + 1] if math.isfinite(v)) / period
    atr[period] = seed
    for idx in range(period + 1, n):
        atr[idx] = ((atr[idx - 1] * (period - 1)) + tr[idx]) / period
    return pd.Series(atr, dtype=float)


def build_stepsto_frame(df, indicator_minutes, kfast, kslow, point, period_atr=10):
    signal_df = build_resampled_frame(df, indicator_minutes)
    close = signal_df['close'].astype(float).reset_index(drop=True)
    atr = atr_wilder(signal_df['high'], signal_df['low'], signal_df['close'], period_atr)
    n = len(signal_df)
    fast = [math.nan] * n
    slow = [math.nan] * n
    min_rates_total = max(2, period_atr)

    if n <= min_rates_total:
        out = signal_df.copy()
        out['fast'] = fast
        out['slow'] = slow
        out['atr'] = list(atr)
        return out

    limit = min_rates_total
    atrmax1 = 0.0
    atrmin1 = 999999999.9
    seed_close = float(close.iloc[limit]) if limit < n else float(close.iloc[-1])
    smin_min1 = seed_close
    smax_min1 = seed_close
    smin_max1 = seed_close
    smax_max1 = seed_close
    smin_mid1 = seed_close
    smax_mid1 = seed_close
    trend_max1 = 1
    trend_min1 = -1
    trend_mid1 = 1

    for idx in range(limit, n):
        atr_value = float(atr.iloc[idx]) if math.isfinite(float(atr.iloc[idx])) else math.nan
        if not math.isfinite(atr_value):
            continue
        atrmax0 = max(atr_value, atrmax1)
        atrmin0 = min(atr_value, atrmin1)
        step_size_min = float(kfast) * atrmin0
        step_size_max = float(kfast) * atrmax0
        step_size_mid = float(kfast) * 0.5 * float(kslow) * (atrmax0 + atrmin0)

        price = float(close.iloc[idx])
        smax_min0 = price + 2.0 * step_size_min
        smin_min0 = price - 2.0 * step_size_min
        smax_max0 = price + 2.0 * step_size_max
        smin_max0 = price - 2.0 * step_size_max
        smax_mid0 = price + 2.0 * step_size_mid
        smin_mid0 = price - 2.0 * step_size_mid

        trend_min0 = trend_min1
        trend_max0 = trend_max1
        trend_mid0 = trend_mid1
        if price > smax_min1:
            trend_min0 = 1
        if price < smin_min1:
            trend_min0 = -1
        if price > smax_max1:
            trend_max0 = 1
        if price < smin_max1:
            trend_max0 = -1
        if price > smax_mid1:
            trend_mid0 = 1
        if price < smin_mid1:
            trend_mid0 = -1

        if trend_min0 > 0 and smin_min0 < smin_min1:
            smin_min0 = smin_min1
        if trend_min0 < 0 and smax_min0 > smax_min1:
            smax_min0 = smax_min1
        if trend_max0 > 0 and smin_max0 < smin_max1:
            smin_max0 = smin_max1
        if trend_max0 < 0 and smax_max0 > smax_max1:
            smax_max0 = smax_max1
        if trend_mid0 > 0 and smin_mid0 < smin_mid1:
            smin_mid0 = smin_mid1
        if trend_mid0 < 0 and smax_mid0 > smax_mid1:
            smax_mid0 = smax_mid1

        linemin = smin_min0 + step_size_min if trend_min0 > 0 else smax_min0 - step_size_min
        linemax = smin_max0 + step_size_max if trend_max0 > 0 else smax_max0 - step_size_max
        linemid = smin_mid0 + step_size_mid if trend_mid0 > 0 else smax_mid0 - step_size_mid
        bsmin = linemax - step_size_max
        bsmax = linemax + step_size_max
        denom = bsmax - bsmin
        if denom == 0:
            sto1 = 0.5
            sto2 = 0.5
        else:
            sto1 = (linemin - bsmin) / denom
            sto2 = (linemid - bsmin) / denom
        fast[idx] = sto1 * 100.0
        slow[idx] = sto2 * 100.0

        atrmax1 = atrmax0
        atrmin1 = atrmin0
        smin_min1 = smin_min0
        smax_min1 = smax_min0
        smin_max1 = smin_max0
        smax_max1 = smax_max0
        smin_mid1 = smin_mid0
        smax_mid1 = smax_mid0
        trend_max1 = trend_max0
        trend_min1 = trend_min0
        trend_mid1 = trend_mid0

    out = signal_df.copy()
    out['fast'] = fast
    out['slow'] = slow
    out['atr'] = list(atr)
    return out


class StepStoStrategy(bt.Strategy):
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
        kfast=1.0,
        kslow=1.0,
        period_atr=10,
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
        fast_recent = self._line_value(self.signal.fast, recent_ago)
        fast_prev = self._line_value(self.signal.fast, prev_ago)
        slow_recent = self._line_value(self.signal.slow, recent_ago)
        slow_prev = self._line_value(self.signal.slow, prev_ago)
        if not all(math.isfinite(v) for v in [fast_recent, fast_prev, slow_recent, slow_prev]):
            return

        buy_signal = slow_prev > 50 and fast_prev > slow_prev and fast_recent <= slow_recent
        sell_signal = slow_prev < 50 and fast_prev < slow_prev and fast_recent >= slow_recent
        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} fast={fast_prev:.2f} slow={slow_prev:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} fast={fast_prev:.2f} slow={slow_prev:.2f}')
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
