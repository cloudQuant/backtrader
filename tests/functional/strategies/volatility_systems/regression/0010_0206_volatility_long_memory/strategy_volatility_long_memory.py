from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    df['datetime'] = parsed
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def hurst_exponent(values, min_lag=2, max_lag=20):
    series = np.asarray(values, dtype=float)
    series = series[np.isfinite(series)]
    if len(series) <= max_lag + 1:
        return np.nan
    upper_lag = min(int(max_lag), max(3, len(series) // 2))
    lags = np.arange(int(min_lag), upper_lag + 1)
    if len(lags) < 3:
        return np.nan
    tau = []
    for lag in lags:
        diffs = series[lag:] - series[:-lag]
        std = np.std(diffs)
        tau.append(std if std > 0 else np.nan)
    tau = np.asarray(tau, dtype=float)
    valid = np.isfinite(tau) & (tau > 0)
    if valid.sum() < 3:
        return np.nan
    slope, _ = np.polyfit(np.log(lags[valid]), np.log(tau[valid]), 1)
    return float(np.clip(slope, 0.0, 1.0))


def compute_rsi(close, period):
    delta = close.diff()
    gain = delta.clip(lower=0.0).rolling(period).mean()
    loss = (-delta.clip(upper=0.0)).rolling(period).mean()
    rs = gain / loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def prepare_volatility_long_memory_features(price_df, params):
    out = price_df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    vol_window = int(params.get('vol_window', 21))
    hurst_window = int(params.get('hurst_window', 252))
    regime_compare_window = int(params.get('regime_compare_window', 63))
    min_lag = int(params.get('min_lag', 2))
    max_lag = int(params.get('max_lag', 20))
    fast_ma_period = int(params.get('fast_ma_period', 20))
    slow_ma_period = int(params.get('slow_ma_period', 50))
    momentum_window = int(params.get('momentum_window', 21))
    mean_window = int(params.get('mean_window', 20))
    rsi_period = int(params.get('rsi_period', 14))
    trend_threshold = float(params.get('trend_threshold', 0.55))
    trend_strong_threshold = float(params.get('trend_strong_threshold', 0.60))
    mean_reversion_threshold = float(params.get('mean_reversion_threshold', 0.45))
    mean_reversion_strong_threshold = float(params.get('mean_reversion_strong_threshold', 0.40))
    regime_change_threshold = float(params.get('regime_change_threshold', 0.10))
    zscore_entry_threshold = float(params.get('zscore_entry_threshold', 1.5))
    zscore_exit_threshold = float(params.get('zscore_exit_threshold', 0.35))
    neutral_exposure = float(params.get('neutral_exposure', 0.25))
    moderate_exposure = float(params.get('moderate_exposure', 0.75))
    strong_exposure = float(params.get('strong_exposure', 1.0))
    regime_change_exposure = float(params.get('regime_change_exposure', 0.25))
    allow_short = bool(params.get('allow_short', True))

    out['returns'] = out['close'].pct_change()
    out['volatility'] = out['returns'].rolling(vol_window).std() * np.sqrt(252.0)
    out['hurst'] = out['volatility'].rolling(hurst_window).apply(
        lambda arr: hurst_exponent(arr, min_lag=min_lag, max_lag=max_lag), raw=True
    )
    out['previous_hurst'] = out['hurst'].shift(regime_compare_window)
    out['hurst_change'] = out['hurst'] - out['previous_hurst']
    out['regime_change'] = (out['hurst_change'].abs() > regime_change_threshold).astype(float)

    out['fast_ma'] = out['close'].rolling(fast_ma_period).mean()
    out['slow_ma'] = out['close'].rolling(slow_ma_period).mean()
    out['momentum'] = out['close'].pct_change(momentum_window)
    out['mean_line'] = out['close'].rolling(mean_window).mean()
    out['std_line'] = out['close'].rolling(mean_window).std().replace(0.0, np.nan)
    out['zscore'] = (out['close'] - out['mean_line']) / out['std_line']
    out['rsi'] = compute_rsi(out['close'], rsi_period)

    out['trend_signal'] = 0.0
    trend_long = (out['fast_ma'] > out['slow_ma']) & (out['momentum'] > 0)
    trend_short = (out['fast_ma'] < out['slow_ma']) & (out['momentum'] < 0)
    out.loc[trend_long, 'trend_signal'] = 1.0
    out.loc[trend_short & allow_short, 'trend_signal'] = -1.0

    out['mean_reversion_signal'] = 0.0
    mr_long = (out['zscore'] <= -zscore_entry_threshold) | (out['rsi'] <= float(params.get('rsi_oversold', 35)))
    mr_short = (out['zscore'] >= zscore_entry_threshold) | (out['rsi'] >= float(params.get('rsi_overbought', 65)))
    mr_flat = out['zscore'].abs() <= zscore_exit_threshold
    out.loc[mr_long, 'mean_reversion_signal'] = 1.0
    out.loc[mr_short & allow_short, 'mean_reversion_signal'] = -1.0
    out.loc[mr_flat, 'mean_reversion_signal'] = 0.0

    out['regime_code'] = 0.0
    out.loc[out['hurst'] > trend_threshold, 'regime_code'] = 1.0
    out.loc[out['hurst'] < mean_reversion_threshold, 'regime_code'] = -1.0

    out['target_exposure'] = 0.0
    trend_strong_mask = out['hurst'] > trend_strong_threshold
    trend_mask = out['hurst'] > trend_threshold
    mr_strong_mask = out['hurst'] < mean_reversion_strong_threshold
    mr_mask = out['hurst'] < mean_reversion_threshold

    out.loc[trend_mask, 'target_exposure'] = out.loc[trend_mask, 'trend_signal'] * moderate_exposure
    out.loc[trend_strong_mask, 'target_exposure'] = out.loc[trend_strong_mask, 'trend_signal'] * strong_exposure
    out.loc[mr_mask, 'target_exposure'] = out.loc[mr_mask, 'mean_reversion_signal'] * moderate_exposure
    out.loc[mr_strong_mask, 'target_exposure'] = out.loc[mr_strong_mask, 'mean_reversion_signal'] * strong_exposure

    neutral_mask = out['regime_code'] == 0.0
    neutral_direction = np.sign(out['close'] - out['slow_ma']).fillna(0.0)
    if not allow_short:
        neutral_direction = neutral_direction.clip(lower=0.0)
    out.loc[neutral_mask, 'target_exposure'] = neutral_direction[neutral_mask] * neutral_exposure

    regime_change_mask = out['regime_change'] > 0.5
    out.loc[regime_change_mask, 'target_exposure'] = np.sign(out.loc[regime_change_mask, 'target_exposure']) * regime_change_exposure

    out['target_exposure'] = out['target_exposure'].fillna(0.0)
    out['signal_change'] = (out['target_exposure'].diff().abs() >= float(params.get('min_exposure_change', 0.05))).astype(float)
    out.iloc[0, out.columns.get_loc('signal_change')] = 1.0

    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'volatility', 'hurst', 'previous_hurst', 'hurst_change', 'regime_change',
        'fast_ma', 'slow_ma', 'momentum', 'mean_line', 'zscore', 'rsi',
        'regime_code', 'trend_signal', 'mean_reversion_signal', 'target_exposure', 'signal_change',
    ]
    return out[columns].dropna().copy()


class VolatilityLongMemoryFeed(bt.feeds.PandasData):
    lines = (
        'volatility', 'hurst', 'previous_hurst', 'hurst_change', 'regime_change',
        'fast_ma', 'slow_ma', 'momentum', 'mean_line', 'zscore', 'rsi',
        'regime_code', 'trend_signal', 'mean_reversion_signal', 'target_exposure', 'signal_change',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('volatility', 6), ('hurst', 7), ('previous_hurst', 8), ('hurst_change', 9), ('regime_change', 10),
        ('fast_ma', 11), ('slow_ma', 12), ('momentum', 13), ('mean_line', 14), ('zscore', 15), ('rsi', 16),
        ('regime_code', 17), ('trend_signal', 18), ('mean_reversion_signal', 19), ('target_exposure', 20), ('signal_change', 21),
    )


class VolatilityLongMemoryStrategy(bt.Strategy):
    params = dict(
        vol_window=21,
        hurst_window=252,
        regime_compare_window=63,
        min_lag=2,
        max_lag=20,
        trend_threshold=0.55,
        trend_strong_threshold=0.6,
        mean_reversion_threshold=0.45,
        mean_reversion_strong_threshold=0.4,
        regime_change_threshold=0.1,
        fast_ma_period=20,
        slow_ma_period=50,
        momentum_window=21,
        mean_window=20,
        zscore_entry_threshold=1.5,
        zscore_exit_threshold=0.35,
        rsi_period=14,
        rsi_oversold=35,
        rsi_overbought=65,
        neutral_exposure=0.25,
        moderate_exposure=0.75,
        strong_exposure=1.0,
        regime_change_exposure=0.25,
        min_exposure_change=0.05,
        allow_short=True,
    )

    def __init__(self):
        self.bar_num = 0
        self.pending_order = None
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.signal_change_count = 0
        self.regime_change_count = 0
        self.trend_days = 0
        self.mean_reversion_days = 0
        self.neutral_days = 0
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))

        regime_code = float(self.data.regime_code[0])
        if regime_code > 0.5:
            self.trend_days += 1
        elif regime_code < -0.5:
            self.mean_reversion_days += 1
        else:
            self.neutral_days += 1

        if float(self.data.regime_change[0]) > 0.5:
            self.regime_change_count += 1

        if self.pending_order is not None:
            return
        if float(self.data.signal_change[0]) <= 0.5:
            return

        self.signal_change_count += 1
        self.pending_order = self.order_target_percent(target=float(self.data.target_exposure[0]))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
