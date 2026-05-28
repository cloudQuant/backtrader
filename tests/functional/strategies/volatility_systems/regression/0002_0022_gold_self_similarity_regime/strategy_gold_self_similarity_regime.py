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


def hurst_exponent(values):
    series = np.asarray(values, dtype=float)
    if len(series) < 32 or np.isnan(series).any():
        return np.nan
    max_lag = min(20, len(series) // 2)
    if max_lag < 4:
        return np.nan
    lags = np.arange(2, max_lag + 1)
    tau = []
    for lag in lags:
        diff = series[lag:] - series[:-lag]
        std = np.std(diff)
        tau.append(std if std > 0 else np.nan)
    tau = np.asarray(tau, dtype=float)
    valid = np.isfinite(tau) & (tau > 0)
    if valid.sum() < 3:
        return np.nan
    reg = np.polyfit(np.log(lags[valid]), np.log(tau[valid]), 1)
    return float(reg[0])


def prepare_self_similarity_features(price_df, params):
    hurst_window = int(params.get('hurst_window', 128))
    trend_threshold = float(params.get('trend_threshold', 0.55))
    mean_revert_threshold = float(params.get('mean_revert_threshold', 0.45))
    breakout_lookback = int(params.get('breakout_lookback', 20))
    mean_window = int(params.get('mean_window', 20))
    zscore_entry_threshold = float(params.get('zscore_entry_threshold', 1.5))
    zscore_exit_threshold = float(params.get('zscore_exit_threshold', 0.2))
    out = price_df.copy()
    out['hurst'] = out['close'].rolling(hurst_window).apply(hurst_exponent, raw=False)
    out['regime_code'] = 0.0
    out.loc[out['hurst'] > trend_threshold, 'regime_code'] = 1.0
    out.loc[out['hurst'] < mean_revert_threshold, 'regime_code'] = -1.0
    out['regime_strength'] = ((out['hurst'] - 0.5).abs() / 0.5).clip(lower=0.0, upper=1.0)
    out['breakout_high'] = out['high'].shift(1).rolling(breakout_lookback).max()
    out['breakout_low'] = out['low'].shift(1).rolling(int(params.get('trend_exit_lookback', 10))).min()
    out['mean_line'] = out['close'].rolling(mean_window).mean()
    out['std_line'] = out['close'].rolling(mean_window).std().replace(0, np.nan)
    out['zscore'] = (out['close'] - out['mean_line']) / out['std_line']
    out['trend_entry'] = ((out['regime_code'] == 1.0) & (out['close'] > out['breakout_high'])).astype(float)
    out['trend_exit'] = ((out['regime_code'] != 1.0) | (out['close'] < out['breakout_low'])).astype(float)
    out['meanrev_entry'] = ((out['regime_code'] == -1.0) & (out['zscore'] <= -zscore_entry_threshold)).astype(float)
    out['meanrev_exit'] = ((out['regime_code'] != -1.0) | (out['zscore'] >= -zscore_exit_threshold)).astype(float)
    return out.dropna(subset=['hurst', 'breakout_high', 'mean_line', 'zscore'])


class GoldSelfSimilarityFeed(bt.feeds.PandasData):
    lines = ('hurst', 'regime_code', 'regime_strength', 'breakout_high', 'breakout_low', 'mean_line', 'zscore', 'trend_entry', 'trend_exit', 'meanrev_entry', 'meanrev_exit')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('hurst', 6), ('regime_code', 7), ('regime_strength', 8), ('breakout_high', 9), ('breakout_low', 10), ('mean_line', 11), ('zscore', 12), ('trend_entry', 13), ('trend_exit', 14), ('meanrev_entry', 15), ('meanrev_exit', 16),
    )


class GoldSelfSimilarityRegimeStrategy(bt.Strategy):
    params = dict(
        base_position_pct=0.03,
        max_position_pct=0.05,
        stop_loss_pct=0.03,
        hurst_window=128,
        trend_threshold=0.55,
        mean_revert_threshold=0.45,
        breakout_lookback=20,
        mean_window=20,
        zscore_entry_threshold=1.5,
        zscore_exit_threshold=0.2,
        trend_exit_lookback=10,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_price = None
        self.entry_mode = None
        self.stop_price = None
        self.broker_value_series = []

    def _get_target_pct(self):
        strength = float(self.data.regime_strength[0]) if self.data.regime_strength[0] == self.data.regime_strength[0] else 0.0
        return min(float(self.p.max_position_pct), float(self.p.base_position_pct) * max(strength, 0.5))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        close = float(self.data.close[0])
        low = float(self.data.low[0])
        if self.position:
            if self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.entry_mode == 'trend' and float(self.data.trend_exit[0]) > 0.5:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.entry_mode == 'meanrev' and float(self.data.meanrev_exit[0]) > 0.5:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return
        target_pct = self._get_target_pct()
        if float(self.data.trend_entry[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.order_target_percent(target=target_pct)
            self.entry_price = close
            self.entry_mode = 'trend'
            self.stop_price = close * (1.0 - float(self.p.stop_loss_pct))
            return
        if float(self.data.meanrev_entry[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.order_target_percent(target=target_pct)
            self.entry_price = close
            self.entry_mode = 'meanrev'
            self.stop_price = close * (1.0 - float(self.p.stop_loss_pct))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.entry_mode = None
            self.stop_price = None
