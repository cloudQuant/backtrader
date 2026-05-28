from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    if bar_shift_minutes:
        parsed = parsed + pd.to_timedelta(int(bar_shift_minutes), unit='m')
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


def resample_to_monthly(df):
    monthly = pd.DataFrame({
        'open': df['open'].resample('ME').first(),
        'high': df['high'].resample('ME').max(),
        'low': df['low'].resample('ME').min(),
        'close': df['close'].resample('ME').last(),
        'volume': df['volume'].resample('ME').sum(),
        'openinterest': df['openinterest'].resample('ME').last().fillna(0),
    })
    return monthly.dropna(subset=['open', 'high', 'low', 'close'])


def prepare_factor_timing_data(asset_daily_frames, params):
    monthly_frames = {name: resample_to_monthly(frame) for name, frame in asset_daily_frames.items()}
    common_index = None
    for frame in monthly_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    monthly_frames = {name: frame.loc[common_index].copy() for name, frame in monthly_frames.items()}

    momentum_lookback = int(params.get('momentum_lookback_months', 12))
    valuation_lookback = int(params.get('valuation_lookback_months', 36))
    equity_relative_lookback = int(params.get('equity_relative_lookback_months', 12))
    momentum_threshold = float(params.get('momentum_threshold', 0.0))
    value_zscore_threshold = float(params.get('value_zscore_threshold', -0.5))
    momentum_max_valuation_z = float(params.get('momentum_max_valuation_z', 0.75))
    single_factor_weight = float(params.get('single_factor_weight', 0.5))
    dual_factor_weight = float(params.get('dual_factor_weight', 1.0))

    gold_close = monthly_frames['XAUUSD']['close']
    ivv_close = monthly_frames['IVV']['close']
    gtip_close = monthly_frames['GTIP']['close']

    gold_momentum = gold_close / gold_close.shift(momentum_lookback) - 1.0
    relative_equity = gold_close / gold_close.shift(equity_relative_lookback) - ivv_close / ivv_close.shift(equity_relative_lookback)
    valuation_ratio = gold_close / gtip_close
    valuation_mean = valuation_ratio.rolling(valuation_lookback).mean()
    valuation_std = valuation_ratio.rolling(valuation_lookback).std()
    valuation_zscore = (valuation_ratio - valuation_mean) / valuation_std.replace(0, np.nan)

    value_active = ((valuation_zscore <= value_zscore_threshold) & (relative_equity < 0)).astype(float)
    momentum_active = ((gold_momentum > momentum_threshold) & (valuation_zscore <= momentum_max_valuation_z)).astype(float)
    target_weight = value_active * single_factor_weight + momentum_active * single_factor_weight
    target_weight = target_weight.clip(upper=dual_factor_weight)
    selected_factor = pd.Series('CASH', index=common_index, dtype='object')
    selected_factor.loc[(value_active > 0.5) & (momentum_active < 0.5)] = 'VALUE'
    selected_factor.loc[(value_active < 0.5) & (momentum_active > 0.5)] = 'MOMENTUM'
    selected_factor.loc[(value_active > 0.5) & (momentum_active > 0.5)] = 'BOTH'
    selected_factor_code = selected_factor.map({'CASH': 0, 'VALUE': 1, 'MOMENTUM': 2, 'BOTH': 3}).astype(float)

    signal_df = monthly_frames['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['gold_momentum_12m'] = gold_momentum
    signal_df['relative_equity_12m'] = relative_equity
    signal_df['valuation_ratio'] = valuation_ratio
    signal_df['valuation_zscore'] = valuation_zscore
    signal_df['value_active'] = value_active
    signal_df['momentum_active'] = momentum_active
    signal_df['target_weight'] = target_weight
    signal_df['selected_factor_code'] = selected_factor_code

    summary_df = pd.DataFrame({
        'gold_momentum_12m': gold_momentum,
        'relative_equity_12m': relative_equity,
        'valuation_ratio': valuation_ratio,
        'valuation_zscore': valuation_zscore,
        'value_active': value_active,
        'momentum_active': momentum_active,
        'target_weight': target_weight,
        'selected_factor': selected_factor,
        'selected_factor_code': selected_factor_code,
    }).dropna(subset=['gold_momentum_12m', 'valuation_zscore'])

    signal_df = signal_df.loc[summary_df.index].copy()
    return signal_df, monthly_frames, summary_df


class GoldFactorTimingSignalFeed(bt.feeds.PandasData):
    lines = (
        'gold_momentum_12m', 'relative_equity_12m', 'valuation_ratio', 'valuation_zscore',
        'value_active', 'momentum_active', 'target_weight', 'selected_factor_code',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('gold_momentum_12m', 6), ('relative_equity_12m', 7), ('valuation_ratio', 8), ('valuation_zscore', 9),
        ('value_active', 10), ('momentum_active', 11), ('target_weight', 12), ('selected_factor_code', 13),
    )


class GoldFactorTimingStrategy(bt.Strategy):
    params = dict(
        momentum_lookback_months=12,
        valuation_lookback_months=36,
        equity_relative_lookback_months=12,
        momentum_threshold=0.0,
        value_zscore_threshold=-0.5,
        momentum_max_valuation_z=0.75,
        single_factor_weight=0.5,
        dual_factor_weight=1.0,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.gold = self.getdatabyname('XAUUSD')
        self.bar_num = 0
        self.rebalance_count = 0
        self.switch_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order_refs = set()
        self.last_target_weight = None
        self.last_factor_code = None
        self.value_month_count = 0
        self.momentum_month_count = 0
        self.both_month_count = 0
        self.cash_month_count = 0
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order_refs:
            return
        target_weight = float(self.signal.target_weight[0]) if self.signal.target_weight[0] == self.signal.target_weight[0] else 0.0
        factor_code = int(round(float(self.signal.selected_factor_code[0]))) if self.signal.selected_factor_code[0] == self.signal.selected_factor_code[0] else 0
        if factor_code == 0:
            self.cash_month_count += 1
        elif factor_code == 1:
            self.value_month_count += 1
        elif factor_code == 2:
            self.momentum_month_count += 1
        elif factor_code == 3:
            self.both_month_count += 1
        if self.last_target_weight is not None and abs(target_weight - self.last_target_weight) < 1e-9 and factor_code == self.last_factor_code:
            return
        if self.last_factor_code is not None and factor_code != self.last_factor_code:
            self.switch_count += 1
        self.last_target_weight = target_weight
        self.last_factor_code = factor_code
        self.rebalance_count += 1
        current_position = self.getposition(self.gold).size
        order = self.order_target_percent(data=self.gold, target=target_weight)
        if order is not None:
            self.pending_order_refs.add(order.ref)
            if target_weight > 0 and current_position <= 0:
                self.buy_count += 1
            elif target_weight == 0 and current_position > 0:
                self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order_refs.discard(order.ref)
