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


class MultiTrendSignalKvnFeed(btfeeds.PandasData):
    lines = ('buy_arrow', 'sell_arrow', 'adx')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('buy_arrow', 6), ('sell_arrow', 7), ('adx', 8),
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


def adx_wilder(high_series, low_series, close_series, period):
    period = int(period)
    high = pd.Series(high_series, dtype=float).reset_index(drop=True)
    low = pd.Series(low_series, dtype=float).reset_index(drop=True)
    close = pd.Series(close_series, dtype=float).reset_index(drop=True)
    n = len(close)
    tr = [math.nan] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for idx in range(1, n):
        up_move = high.iloc[idx] - high.iloc[idx - 1]
        down_move = low.iloc[idx - 1] - low.iloc[idx]
        plus_dm[idx] = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[idx] = down_move if down_move > up_move and down_move > 0 else 0.0
        tr[idx] = max(
            high.iloc[idx] - low.iloc[idx],
            abs(high.iloc[idx] - close.iloc[idx - 1]),
            abs(low.iloc[idx] - close.iloc[idx - 1]),
        )

    atr = [math.nan] * n
    plus_sm = [math.nan] * n
    minus_sm = [math.nan] * n
    plus_di = [math.nan] * n
    minus_di = [math.nan] * n
    dx = [math.nan] * n
    adx = [math.nan] * n
    if n <= period * 2:
        return pd.Series(adx, dtype=float)

    atr_seed = sum(v for v in tr[1:period + 1] if math.isfinite(v))
    plus_seed = sum(plus_dm[1:period + 1])
    minus_seed = sum(minus_dm[1:period + 1])
    atr[period] = atr_seed
    plus_sm[period] = plus_seed
    minus_sm[period] = minus_seed
    if atr_seed != 0:
        plus_di[period] = 100.0 * plus_seed / atr_seed
        minus_di[period] = 100.0 * minus_seed / atr_seed
        di_sum = plus_di[period] + minus_di[period]
        dx[period] = 100.0 * abs(plus_di[period] - minus_di[period]) / di_sum if di_sum else 0.0

    for idx in range(period + 1, n):
        atr[idx] = atr[idx - 1] - (atr[idx - 1] / period) + (tr[idx] if math.isfinite(tr[idx]) else 0.0)
        plus_sm[idx] = plus_sm[idx - 1] - (plus_sm[idx - 1] / period) + plus_dm[idx]
        minus_sm[idx] = minus_sm[idx - 1] - (minus_sm[idx - 1] / period) + minus_dm[idx]
        if atr[idx] and math.isfinite(atr[idx]):
            plus_di[idx] = 100.0 * plus_sm[idx] / atr[idx]
            minus_di[idx] = 100.0 * minus_sm[idx] / atr[idx]
            di_sum = plus_di[idx] + minus_di[idx]
            dx[idx] = 100.0 * abs(plus_di[idx] - minus_di[idx]) / di_sum if di_sum else 0.0

    first_adx_index = period * 2
    initial_dx = [v for v in dx[period:first_adx_index] if math.isfinite(v)]
    if len(initial_dx) == period:
        adx[first_adx_index - 1] = sum(initial_dx) / period
        for idx in range(first_adx_index, n):
            if math.isfinite(dx[idx]) and math.isfinite(adx[idx - 1]):
                adx[idx] = ((adx[idx - 1] * (period - 1)) + dx[idx]) / period
    return pd.Series(adx, dtype=float)


def build_multitrend_signal_kvn_frame(df, indicator_minutes, k, kstop, kperiod, per_adx, point):
    signal_df = build_resampled_frame(df, indicator_minutes)
    high = signal_df['high'].astype(float).reset_index(drop=True)
    low = signal_df['low'].astype(float).reset_index(drop=True)
    close = signal_df['close'].astype(float).reset_index(drop=True)
    adx = adx_wilder(high, low, close, per_adx)
    n = len(signal_df)
    buy_arrow = [0.0] * n
    sell_arrow = [0.0] * n
    prev_trend = 0
    min_rates_total = int(kperiod + per_adx + 1)

    for idx in range(n):
        adx_value = float(adx.iloc[idx]) if idx < len(adx) and math.isfinite(float(adx.iloc[idx])) else math.nan
        if idx < min_rates_total or not math.isfinite(adx_value) or adx_value <= 0:
            continue
        ssp = int(math.ceil(float(kperiod) / adx_value))
        ssp = max(1, ssp)
        if idx - ssp + 1 < 0:
            continue

        window_high = high.iloc[idx - ssp + 1:idx + 1]
        window_low = low.iloc[idx - ssp + 1:idx + 1]
        avg_range = (window_high - window_low).abs().mean()
        ss_max = window_high.max()
        ss_min = window_low.min()
        swing = (ss_max - ss_min) * float(k) / 100.0
        smin = ss_min + swing
        smax = ss_max - swing
        trend = prev_trend
        val1 = 0.0
        val2 = 0.0

        if close.iloc[idx] < smin:
            trend = -1
            if prev_trend > -1:
                val1 = float(high.iloc[idx]) + avg_range * float(kstop)

        if close.iloc[idx] > smax:
            trend = 1
            if prev_trend < 1:
                val2 = float(low.iloc[idx]) - avg_range * float(kstop)

        buy_arrow[idx] = val2
        sell_arrow[idx] = val1
        prev_trend = trend

    out = signal_df.copy()
    out['buy_arrow'] = buy_arrow
    out['sell_arrow'] = sell_arrow
    out['adx'] = list(adx)
    return out


class MultiTrendSignalKvnStrategy(bt.Strategy):
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
        k=48,
        kstop=0.5,
        kperiod=150,
        per_adx=14,
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
        if len(self.signal) < signal_bar + 2:
            return

        current_signal_len = len(self.signal)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len

        current_ago = signal_bar - 1
        current_buy = self._line_value(self.signal.buy_arrow, current_ago)
        current_sell = self._line_value(self.signal.sell_arrow, current_ago)
        last_trend = 0
        for ago in range(signal_bar + 1, len(self.signal)):
            older_buy = self._line_value(self.signal.buy_arrow, ago - 1)
            if older_buy != 0.0:
                last_trend = 1
                break
            older_sell = self._line_value(self.signal.sell_arrow, ago - 1)
            if older_sell != 0.0:
                last_trend = -1
                break

        buy_signal = current_buy != 0.0
        sell_signal = current_sell != 0.0
        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} arrow={current_buy:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open and last_trend < 0:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} arrow={current_sell:.2f}')
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
            if self.position.size >= 0 and self.p.sell_pos_open and last_trend > 0:
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
