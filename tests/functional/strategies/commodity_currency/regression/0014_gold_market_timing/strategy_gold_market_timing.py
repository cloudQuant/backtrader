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


def _calculate_rsi(close, period):
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    avg_gain = gains.rolling(period).mean()
    avg_loss = losses.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def prepare_gold_market_timing_inputs(price_frame, params):
    sma_fast = int(params.get('sma_fast', 20))
    sma_slow = int(params.get('sma_slow', 100))
    momentum_period = int(params.get('momentum_period', 63))
    vol_window = int(params.get('vol_window', 21))
    vol_lookback = int(params.get('vol_lookback', 252))
    rsi_period = int(params.get('rsi_period', 14))

    signal_df = price_frame[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    close = signal_df['close']
    returns = close.pct_change()

    sma_fast_series = close.rolling(sma_fast).mean()
    sma_slow_series = close.rolling(sma_slow).mean()
    signal_df['sma_signal'] = np.where(sma_fast_series > sma_slow_series, 1.0, -1.0)

    momentum = close.pct_change(momentum_period)
    signal_df['momentum_signal'] = np.where(momentum > 0, 1.0, -1.0)

    annualized_vol = returns.rolling(vol_window).std() * np.sqrt(252)
    vol_percentile = annualized_vol.rolling(vol_lookback).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    signal_df['volatility_signal'] = 0.0
    signal_df.loc[vol_percentile < 0.3, 'volatility_signal'] = 1.0
    signal_df.loc[vol_percentile > 0.7, 'volatility_signal'] = -1.0

    rsi = _calculate_rsi(close, rsi_period)
    signal_df['rsi_signal'] = 0.0
    signal_df.loc[rsi < 30, 'rsi_signal'] = 1.0
    signal_df.loc[rsi > 70, 'rsi_signal'] = -1.0

    signal_df['combined_signal'] = (
        0.3 * signal_df['sma_signal']
        + 0.3 * signal_df['momentum_signal']
        + 0.2 * signal_df['volatility_signal']
        + 0.2 * signal_df['rsi_signal']
    )

    signal_df['target_position'] = 0.0
    signal_df.loc[signal_df['combined_signal'] > 0.5, 'target_position'] = 1.0
    signal_df.loc[(signal_df['combined_signal'] > 0.2) & (signal_df['combined_signal'] <= 0.5), 'target_position'] = 0.75
    signal_df.loc[(signal_df['combined_signal'] > 0.0) & (signal_df['combined_signal'] <= 0.2), 'target_position'] = 0.5
    signal_df.loc[(signal_df['combined_signal'] > -0.2) & (signal_df['combined_signal'] <= 0.0), 'target_position'] = 0.25
    signal_df.loc[signal_df['combined_signal'] <= -0.2, 'target_position'] = 0.0

    signal_df['signal_change'] = signal_df['target_position'].round(8).ne(signal_df['target_position'].shift(1).round(8)).astype(float)
    signal_df = signal_df.dropna()
    return signal_df


class GoldMarketTimingFeed(bt.feeds.PandasData):
    lines = ('sma_signal', 'momentum_signal', 'volatility_signal', 'rsi_signal', 'combined_signal', 'target_position', 'signal_change')
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('sma_signal', 6),
        ('momentum_signal', 7),
        ('volatility_signal', 8),
        ('rsi_signal', 9),
        ('combined_signal', 10),
        ('target_position', 11),
        ('signal_change', 12),
    )


class GoldMarketTimingStrategy(bt.Strategy):
    params = dict(
        sma_fast=20,
        sma_slow=100,
        momentum_period=63,
        vol_window=21,
        vol_lookback=252,
        rsi_period=14,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal_data = self.datas[0]
        self.asset_data = self.datas[1]
        self.pending_order = None
        self.bar_num = 0
        self.rebalance_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal_data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if float(self.signal_data.signal_change[0]) <= 0.5:
            return
        self.rebalance_count += 1
        target = float(self.signal_data.target_position[0])
        self.pending_order = self.order_target_percent(data=self.asset_data, target=target)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if self.pending_order is not None and order.ref == self.pending_order.ref:
            self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
