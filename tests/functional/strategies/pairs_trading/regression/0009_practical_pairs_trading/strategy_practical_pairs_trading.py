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
    if 'time' in df.columns:
        df['datetime'] = pd.to_datetime(df['time'], errors='coerce', utc=True).dt.tz_convert(None)
        if 'volume' not in df.columns:
            df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
        df['openinterest'] = 0
        df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
        df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
        if fromdate is not None:
            df = df[df.index >= fromdate]
        if todate is not None:
            df = df[df.index <= todate]
        return df
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    df['datetime'] = parsed
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


def prepare_pair_inputs(frame_a, frame_b, params):
    aligned_index = frame_a.index.intersection(frame_b.index).sort_values()
    frame_a = frame_a.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    frame_b = frame_b.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    lookback = int(params.get('lookback_bars', 960))
    close_a = frame_a['close'].astype(float)
    close_b = frame_b['close'].astype(float)
    log_a = np.log(close_a.clip(lower=1e-9))
    log_b = np.log(close_b.clip(lower=1e-9))
    ret_a = log_a.diff()
    ret_b = log_b.diff()
    corr = ret_a.rolling(lookback).corr(ret_b)
    beta = log_a.rolling(lookback).cov(log_b) / log_b.rolling(lookback).var()
    spread = log_a - beta * log_b
    spread_mean = spread.rolling(lookback).mean()
    spread_std = spread.rolling(lookback).std().replace(0, np.nan)
    zscore = (spread - spread_mean) / spread_std
    signal_df = pd.DataFrame({'corr': corr, 'beta': beta, 'spread': spread, 'zscore': zscore}, index=aligned_index)
    signal_df = signal_df.replace([np.inf, -np.inf], np.nan).dropna().copy()
    valid_index = signal_df.index
    frame_a = frame_a.loc[valid_index].copy()
    frame_b = frame_b.loc[valid_index].copy()
    return frame_a, frame_b, signal_df


class PracticalPairsTradingStrategy(bt.Strategy):
    params = dict(
        asset_a_symbol='XAUUSD',
        asset_b_symbol='XAGUSD',
        min_correlation=0.6,
        entry_z=2.0,
        exit_z=0.5,
        stop_loss_z=3.5,
        pair_weight=0.20,
        signal_lookup=None,
        lookback_bars=960,
        commission_pct=0.0005,
        annualization_factor=6048,
    )

    def __init__(self):
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.broker_value_series = []
        self.long_spread_days = 0
        self.short_spread_days = 0
        self.flat_days = 0
        self.spread_state = 'flat'

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _target_size(self, data, target_pct):
        broker_value = float(self.broker.getvalue())
        price = float(data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * abs(float(target_pct)) / (price * multiplier)
        size = max(0.01, round(size, 2))
        return size if target_pct >= 0 else -size

    def _apply_targets(self, data_a, data_b, pct_a, pct_b):
        for data, target_pct in ((data_a, pct_a), (data_b, pct_b)):
            current_pos = float(self.getposition(data).size)
            target_size = self._target_size(data, target_pct)
            if abs(target_size - current_pos) < 0.01:
                continue
            if target_size > current_pos:
                self.buy_count += 1
            elif target_size < current_pos:
                self.sell_count += 1
            self._submit(self.order_target_size(data=data, target=target_size))

    def next(self):
        self.bar_num += 1
        data_a = self.datas[0]
        data_b = self.datas[1]
        current_dt = pd.Timestamp(bt.num2date(data_a.datetime[0])).tz_localize(None)
        self.broker_value_series.append((bt.num2date(data_a.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        signal = (self.p.signal_lookup or {}).get(current_dt)
        if signal is None:
            return
        corr = float(signal['corr'])
        beta = float(signal['beta'])
        zscore = float(signal['zscore'])
        if not np.isfinite(corr) or not np.isfinite(beta) or not np.isfinite(zscore) or abs(beta) < 1e-6:
            return
        if corr < float(self.p.min_correlation):
            self.spread_state = 'flat'
            self.flat_days += 1
            self._apply_targets(data_a, data_b, 0.0, 0.0)
            return
        if self.spread_state == 'flat':
            if zscore <= -float(self.p.entry_z):
                self.spread_state = 'long_spread'
            elif zscore >= float(self.p.entry_z):
                self.spread_state = 'short_spread'
        elif self.spread_state == 'long_spread':
            if zscore >= -float(self.p.exit_z) or zscore <= -float(self.p.stop_loss_z):
                self.spread_state = 'flat'
        elif self.spread_state == 'short_spread':
            if zscore <= float(self.p.exit_z) or zscore >= float(self.p.stop_loss_z):
                self.spread_state = 'flat'
        base_weight = float(self.p.pair_weight) / (1.0 + abs(beta))
        hedge_weight = base_weight * abs(beta)
        if self.spread_state == 'long_spread':
            self.long_spread_days += 1
            pct_a, pct_b = base_weight, -hedge_weight
        elif self.spread_state == 'short_spread':
            self.short_spread_days += 1
            pct_a, pct_b = -base_weight, hedge_weight
        else:
            self.flat_days += 1
            pct_a, pct_b = 0.0, 0.0
        self._apply_targets(data_a, data_b, pct_a, pct_b)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
