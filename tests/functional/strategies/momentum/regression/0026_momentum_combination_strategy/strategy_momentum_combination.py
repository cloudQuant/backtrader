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


def prepare_momentum_inputs(asset_map):
    aligned_index = None
    prepared = {}
    for symbol, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    close_df = pd.DataFrame({symbol: frame.loc[aligned_index, 'close'] for symbol, frame in asset_map.items()}, index=aligned_index)
    return prepared, close_df, aligned_index


def build_weight_lookup(close_df, params):
    classic = int(params.get('classic_lookback', 252))
    residual = int(params.get('residual_lookback', 126))
    trend_ma = int(params.get('trend_ma_period', 200))
    overlap = int(params.get('overlap_lookback', 252))
    short = int(params.get('short_lookback', 60))
    rebalance_step = max(1, int(params.get('rebalance_interval_days', 21)))
    returns = close_df.pct_change().fillna(0.0)
    weight_lookup = {}
    start = max(classic, residual, trend_ma, overlap, short) + 1
    for idx in range(start, len(close_df), rebalance_step):
        date = pd.Timestamp(close_df.index[idx]).tz_localize(None)
        window_prices = close_df.iloc[: idx + 1]
        classic_signal = (window_prices.iloc[-1] / window_prices.iloc[-classic] - 1.0).rank(pct=True)
        benchmark_ret = returns['ivv'].iloc[idx - residual:idx]
        residual_signal = {}
        for col in close_df.columns:
            asset_ret = returns[col].iloc[idx - residual:idx]
            beta = np.cov(asset_ret, benchmark_ret)[0, 1] / np.var(benchmark_ret) if np.var(benchmark_ret) > 0 else 0.0
            residual_series = asset_ret - beta * benchmark_ret
            residual_signal[col] = float(residual_series.mean())
        residual_signal = pd.Series(residual_signal).rank(pct=True)
        trend_signal = ((window_prices.iloc[-1] / window_prices.iloc[-trend_ma:].mean()) > 1.0).astype(float)
        overlap_signal = (window_prices.iloc[-1] / window_prices.iloc[-overlap] - 1.0).rolling(1).mean() if isinstance(window_prices.iloc[-1], pd.Series) else None
        overlap_signal = (window_prices.iloc[-1] / window_prices.iloc[-overlap] - 1.0).rank(pct=True)
        short_signal = (window_prices.iloc[-1] / window_prices.iloc[-short] - 1.0).rank(pct=True)
        strategy_scores = pd.DataFrame({
            'classic_momentum': classic_signal,
            'residual_momentum': residual_signal,
            'trend_following': trend_signal,
            'overlapping_momentum': overlap_signal,
            'similar_stock_momentum': short_signal,
        })
        strategy_returns = strategy_scores.sub(0.5).clip(lower=0.0)
        vol = strategy_returns.std().replace(0, np.nan)
        strategy_weights = (1.0 / vol).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        if strategy_weights.sum() <= 0:
            strategy_weights = pd.Series(1.0, index=strategy_returns.columns)
        strategy_weights = strategy_weights / strategy_weights.sum()
        asset_scores = strategy_scores.mul(strategy_weights, axis=1).sum(axis=1)
        positive = asset_scores.clip(lower=asset_scores.quantile(0.5))
        if positive.sum() <= 0:
            asset_weights = pd.Series(1.0 / len(asset_scores), index=asset_scores.index)
        else:
            asset_weights = positive / positive.sum()
        weight_lookup[date] = asset_weights.to_dict()
    return weight_lookup


class MomentumCombinationStrategy(bt.Strategy):
    params = dict(
        weight_lookup=None,
        classic_lookback=252,
        residual_lookback=126,
        trend_ma_period=200,
        overlap_lookback=252,
        short_lookback=60,
        rebalance_interval_days=21,
        commission_pct=0.0005,
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
        self.rebalance_count = 0

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
        current_dt = pd.Timestamp(bt.num2date(self.datas[0].datetime[0])).tz_localize(None)
        self.broker_value_series.append((bt.num2date(self.datas[0].datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        weights = (self.p.weight_lookup or {}).get(current_dt)
        if not weights:
            return
        self.rebalance_count += 1
        for data in self.datas:
            target_pct = float(weights.get(data._name, 0.0))
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
