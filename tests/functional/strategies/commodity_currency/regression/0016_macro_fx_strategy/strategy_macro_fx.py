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


def _zscore(series, lookback):
    rolling_mean = series.rolling(lookback).mean()
    rolling_std = series.rolling(lookback).std().replace(0, np.nan)
    return (series - rolling_mean) / rolling_std


def prepare_macro_fx_data(pair_map, macro_map, params):
    aligned_index = None
    prepared = {}
    macro_lookback = int(params.get('macro_lookback', 63))
    pair_trend_lookback = int(params.get('pair_trend_lookback', 63))
    zscore_lookback = int(params.get('zscore_lookback', 126))
    signal_threshold = float(params.get('signal_threshold', 0.5))
    max_pair_weight = float(params.get('max_pair_weight', 0.25))
    factor_weights = params.get('factor_weights', {}) or {}
    pair_betas = params.get('pair_betas', {}) or {}

    all_frames = list(pair_map.values()) + list(macro_map.values())
    for frame in all_frames:
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()

    ivv = macro_map['IVV'].loc[aligned_index].copy()
    ief = macro_map['IEF'].loc[aligned_index].copy()
    growth_factor = _zscore(ivv['close'].pct_change(macro_lookback), zscore_lookback)
    rates_factor = _zscore(-ief['close'].pct_change(macro_lookback), zscore_lookback)

    for symbol, frame in pair_map.items():
        px = frame.loc[aligned_index].copy()
        pair_trend = _zscore(px['close'].pct_change(pair_trend_lookback), zscore_lookback)
        beta = float(pair_betas.get(symbol, 1.0))
        raw_signal = (
            float(factor_weights.get('growth', 0.4)) * growth_factor * beta +
            float(factor_weights.get('rates', 0.35)) * rates_factor * beta +
            float(factor_weights.get('trend', 0.25)) * pair_trend
        )
        target_percent = raw_signal.clip(lower=-signal_threshold, upper=signal_threshold) / max(signal_threshold, 1e-6) * max_pair_weight
        prepared[symbol] = px[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
        prepared[symbol]['growth_factor'] = growth_factor.astype(float)
        prepared[symbol]['rates_factor'] = rates_factor.astype(float)
        prepared[symbol]['pair_trend'] = pair_trend.astype(float)
        prepared[symbol]['macro_signal'] = raw_signal.astype(float)
        prepared[symbol]['target_percent'] = target_percent.astype(float)
    score_df = pd.DataFrame({symbol: frame['macro_signal'] for symbol, frame in prepared.items()}, index=aligned_index)
    return prepared, score_df.dropna(how='all')


class MacroFXFeed(bt.feeds.PandasData):
    lines = ('growth_factor', 'rates_factor', 'pair_trend', 'macro_signal', 'target_percent')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('growth_factor', 6), ('rates_factor', 7), ('pair_trend', 8), ('macro_signal', 9), ('target_percent', 10),
    )


class MacroFXStrategy(bt.Strategy):
    params = dict(
        rebalance_interval_days=21,
        macro_lookback=63,
        pair_trend_lookback=63,
        zscore_lookback=126,
        signal_threshold=0.5,
        max_pair_weight=0.25,
        factor_weights={'growth': 0.4, 'rates': 0.35, 'trend': 0.25},
        pair_betas={'EURUSD': 0.6, 'AUDUSD': 1.0, 'NZDUSD': 1.0, 'GBPUSD': 0.8},
        commission_pct=0.0002,
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
        self.long_signal_days = 0
        self.short_signal_days = 0
        self.neutral_signal_days = 0

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

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.datas[0].datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        for data in self.datas:
            target_pct = float(data.target_percent[0]) if data.target_percent[0] == data.target_percent[0] else 0.0
            if target_pct > 0:
                self.long_signal_days += 1
            elif target_pct < 0:
                self.short_signal_days += 1
            else:
                self.neutral_signal_days += 1
            current_pos = float(self.getposition(data).size)
            target_size = self._target_size(data, target_pct)
            if abs(target_size - current_pos) < 0.01:
                continue
            if target_size > current_pos:
                self.buy_count += 1
            elif target_size < current_pos:
                self.sell_count += 1
            self._submit(self.order_target_size(data=data, target=target_size))

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
