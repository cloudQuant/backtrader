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


class AdxSmoothedFeed(btfeeds.PandasData):
    lines = ('di_plus', 'di_minus', 'adx_value')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('di_plus', 6), ('di_minus', 7), ('adx_value', 8),
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


def adx_components(df, period):
    period = int(period)
    high = df['high'].astype(float).reset_index(drop=True)
    low = df['low'].astype(float).reset_index(drop=True)
    close = df['close'].astype(float).reset_index(drop=True)
    n = len(df)

    tr = [math.nan] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up_move = high.iloc[i] - high.iloc[i - 1]
        down_move = low.iloc[i - 1] - low.iloc[i]
        plus_dm[i] = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0.0
        tr[i] = max(
            high.iloc[i] - low.iloc[i],
            abs(high.iloc[i] - close.iloc[i - 1]),
            abs(low.iloc[i] - close.iloc[i - 1]),
        )

    atr = [math.nan] * n
    plus_sm = [math.nan] * n
    minus_sm = [math.nan] * n
    if n <= period:
        return pd.Series([math.nan] * n), pd.Series([math.nan] * n), pd.Series([math.nan] * n)

    atr[period] = sum(v for v in tr[1:period + 1] if math.isfinite(v))
    plus_sm[period] = sum(plus_dm[1:period + 1])
    minus_sm[period] = sum(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        atr[i] = atr[i - 1] - atr[i - 1] / period + tr[i]
        plus_sm[i] = plus_sm[i - 1] - plus_sm[i - 1] / period + plus_dm[i]
        minus_sm[i] = minus_sm[i - 1] - minus_sm[i - 1] / period + minus_dm[i]

    plus_di = [math.nan] * n
    minus_di = [math.nan] * n
    dx = [math.nan] * n
    for i in range(period, n):
        if not atr[i] or not math.isfinite(atr[i]):
            continue
        plus_di[i] = 100.0 * plus_sm[i] / atr[i]
        minus_di[i] = 100.0 * minus_sm[i] / atr[i]
        denom = plus_di[i] + minus_di[i]
        if denom:
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / denom

    adx = [math.nan] * n
    adx_start = period * 2
    if n > adx_start:
        window = [v for v in dx[period:adx_start] if math.isfinite(v)]
        if window:
            adx[adx_start - 1] = sum(window) / len(window)
        for i in range(adx_start, n):
            if math.isfinite(dx[i]) and math.isfinite(adx[i - 1]):
                adx[i] = ((adx[i - 1] * (period - 1)) + dx[i]) / period

    return pd.Series(plus_di), pd.Series(minus_di), pd.Series(adx)


def build_adx_smoothed_frame(df, indicator_minutes, adx_period, alpha1, alpha2):
    signal_df = build_resampled_frame(df, indicator_minutes)
    dip_raw, dim_raw, adx_raw = adx_components(signal_df, adx_period)
    n = len(signal_df)
    di_plus = [math.nan] * n
    di_minus = [math.nan] * n
    adx_value = [math.nan] * n
    smooth_plus = 0.0
    smooth_minus = 0.0
    smooth_adx = 0.0
    out_plus_prev = 0.0
    out_minus_prev = 0.0
    out_adx_prev = 0.0

    for idx in range(n):
        dip0 = float(dip_raw.iloc[idx]) if math.isfinite(float(dip_raw.iloc[idx])) else math.nan
        dim0 = float(dim_raw.iloc[idx]) if math.isfinite(float(dim_raw.iloc[idx])) else math.nan
        adx0 = float(adx_raw.iloc[idx]) if math.isfinite(float(adx_raw.iloc[idx])) else math.nan
        dip1 = float(dip_raw.iloc[idx - 1]) if idx > 0 and math.isfinite(float(dip_raw.iloc[idx - 1])) else 0.0
        dim1 = float(dim_raw.iloc[idx - 1]) if idx > 0 and math.isfinite(float(dim_raw.iloc[idx - 1])) else 0.0
        adx1 = float(adx_raw.iloc[idx - 1]) if idx > 0 and math.isfinite(float(adx_raw.iloc[idx - 1])) else 0.0
        if not all(math.isfinite(v) for v in [dip0, dim0, adx0]):
            continue

        smooth_plus = 2.0 * dip0 + (float(alpha1) - 2.0) * dip1 + (1.0 - float(alpha1)) * smooth_plus
        smooth_minus = 2.0 * dim0 + (float(alpha1) - 2.0) * dim1 + (1.0 - float(alpha1)) * smooth_minus
        smooth_adx = 2.0 * adx0 + (float(alpha1) - 2.0) * adx1 + (1.0 - float(alpha1)) * smooth_adx

        out_plus_prev = float(alpha2) * smooth_plus + (1.0 - float(alpha2)) * out_plus_prev
        out_minus_prev = float(alpha2) * smooth_minus + (1.0 - float(alpha2)) * out_minus_prev
        out_adx_prev = float(alpha2) * smooth_adx + (1.0 - float(alpha2)) * out_adx_prev

        di_plus[idx] = out_plus_prev
        di_minus[idx] = out_minus_prev
        adx_value[idx] = out_adx_prev

    signal_df = signal_df.copy()
    signal_df['di_plus'] = di_plus
    signal_df['di_minus'] = di_minus
    signal_df['adx_value'] = adx_value
    return signal_df


class AdxSmoothedStrategy(bt.Strategy):
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
        adx_period=14,
        alpha1=0.25,
        alpha2=0.33,
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
        plus_recent = self._line_value(self.signal.di_plus, recent_ago)
        minus_recent = self._line_value(self.signal.di_minus, recent_ago)
        plus_prev = self._line_value(self.signal.di_plus, prev_ago)
        minus_prev = self._line_value(self.signal.di_minus, prev_ago)
        if not all(math.isfinite(v) for v in [plus_recent, minus_recent, plus_prev, minus_prev]):
            return

        buy_signal = plus_recent > minus_recent and plus_prev <= minus_prev
        sell_signal = plus_recent < minus_recent and plus_prev >= minus_prev
        if not buy_signal and not sell_signal:
            return

        close_price = float(self.base.close[0])
        size = self._position_size(close_price)
        if size <= 0:
            return

        if buy_signal:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} dip={plus_recent:.2f} dim={minus_recent:.2f}')
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return

        if sell_signal:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} dip={plus_recent:.2f} dim={minus_recent:.2f}')
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
