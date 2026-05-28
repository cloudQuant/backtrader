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


def prepare_gap_n_go_features(df, params):
    out = df.copy()
    low_window = int(params.get('low_window', 50))
    atr_window = int(params.get('atr_window', 14))
    gap_threshold_pct = float(params.get('gap_threshold_pct', 0.003))
    gap_atr_multiple = float(params.get('gap_atr_multiple', 0.5))
    hold_days = int(params.get('hold_days', 2))
    short_target_pct = float(params.get('short_target_pct', 1.0))

    out['prev_close'] = out['close'].shift(1)
    out['prior_50d_low'] = out['close'].shift(1).rolling(low_window).min()
    out['new_50d_low'] = (out['close'] < out['prior_50d_low']).astype(float)

    true_range = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['prev_close']).abs(),
        (out['low'] - out['prev_close']).abs(),
    ], axis=1).max(axis=1)
    out['atr'] = true_range.rolling(atr_window).mean()

    out['prior_day_new_low'] = out['new_50d_low'].shift(1).fillna(0.0)
    out['gap_up_abs'] = out['open'] - out['prev_close']
    out['gap_up_pct'] = out['gap_up_abs'] / out['prev_close']
    pct_gap_trigger = out['gap_up_abs'] > (out['prev_close'] * gap_threshold_pct)
    atr_gap_trigger = out['gap_up_abs'] > (out['atr'] * gap_atr_multiple)
    out['significant_gap_up'] = (pct_gap_trigger | atr_gap_trigger).astype(float)
    out['gap_unfilled'] = (out['close'] > out['prev_close']).astype(float)
    out['close_above_open'] = (out['close'] > out['open']).astype(float)

    out['setup_signal'] = (
        (out['prior_day_new_low'] > 0.5)
        & (out['significant_gap_up'] > 0.5)
        & (out['gap_unfilled'] > 0.5)
        & (out['close_above_open'] > 0.5)
    ).astype(float)

    exit_signal = np.zeros(len(out), dtype=float)
    setup_indices = np.where(out['setup_signal'].values > 0.5)[0]
    for idx in setup_indices:
        exit_idx = idx + hold_days
        if exit_idx < len(out):
            exit_signal[exit_idx] = 1.0
    out['exit_signal'] = exit_signal
    out['target_pct'] = np.where(out['setup_signal'] > 0.5, -abs(short_target_pct), np.nan)

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'prior_50d_low', 'new_50d_low', 'prior_day_new_low', 'atr', 'gap_up_pct', 'significant_gap_up', 'gap_unfilled', 'close_above_open', 'setup_signal', 'exit_signal', 'target_pct']].copy()
    return out.dropna(subset=['prior_50d_low', 'atr'])


class GapNGoFadeFeed(bt.feeds.PandasData):
    lines = ('new_50d_low', 'prior_day_new_low', 'atr', 'gap_up_pct', 'significant_gap_up', 'gap_unfilled', 'close_above_open', 'setup_signal', 'exit_signal', 'target_pct')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('new_50d_low', 7), ('prior_day_new_low', 8), ('atr', 9), ('gap_up_pct', 10), ('significant_gap_up', 11), ('gap_unfilled', 12), ('close_above_open', 13), ('setup_signal', 14), ('exit_signal', 15), ('target_pct', 16),
    )


class GapNGoFadeStrategy(bt.Strategy):
    params = dict(
        low_window=50,
        atr_window=14,
        gap_threshold_pct=0.003,
        gap_atr_multiple=0.5,
        hold_days=2,
        short_target_pct=1.0,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if not self.position and float(self.data.setup_signal[0]) > 0.5:
            self.sell_count += 1
            self.pending_order = self.order_target_percent(target=float(self.data.target_pct[0]))
            return
        if self.position and self.position.size < 0 and float(self.data.exit_signal[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.close()

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
