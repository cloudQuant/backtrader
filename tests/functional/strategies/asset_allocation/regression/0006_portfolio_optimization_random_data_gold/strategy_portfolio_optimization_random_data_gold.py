from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSETS = ['XAUUSD', 'XAGUSD', 'GDX']


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


def _normalize_weights(weights, min_weight=0.0, max_weight=1.0):
    clipped = np.clip(np.asarray(weights, dtype=float), min_weight, max_weight)
    total = float(clipped.sum())
    if not np.isfinite(total) or total <= 0:
        return np.ones_like(clipped) / len(clipped)
    return clipped / total


def _markowitz_optimize(mu, cov, min_weight=0.0, max_weight=1.0):
    n_assets = len(mu)
    try:
        raw = np.linalg.pinv(cov).dot(mu)
    except Exception:
        raw = np.ones(n_assets)
    if not np.all(np.isfinite(raw)):
        raw = np.ones(n_assets)
    return _normalize_weights(raw, min_weight=min_weight, max_weight=max_weight)


def _handcraft_weights(corr_matrix, vols, min_weight=0.0, max_weight=1.0):
    avg_corr = corr_matrix.mean(axis=1).to_numpy(dtype=float)
    inv_vol = 1.0 / np.maximum(vols.to_numpy(dtype=float), 1e-8)
    score = inv_vol / np.maximum(avg_corr, 0.1)
    return _normalize_weights(score, min_weight=min_weight, max_weight=max_weight)


def _compute_weights(window_returns, params):
    method = str(params.get('method', 'shrinkage')).lower()
    min_weight = float(params.get('min_weight', 0.0))
    max_weight = float(params.get('max_weight', 1.0))
    vols = window_returns.std().replace(0, np.nan)
    vols = vols.fillna(vols[vols > 0].mean() if (vols > 0).any() else 1.0)
    corr = window_returns.corr().fillna(0.0)
    mean_returns = window_returns.mean().fillna(0.0)
    sharpe = (mean_returns / vols.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    if method == 'equal':
        return pd.Series(np.ones(len(ASSETS)) / len(ASSETS), index=ASSETS)
    if method == 'handcraft':
        return pd.Series(_handcraft_weights(corr, vols, min_weight=min_weight, max_weight=max_weight), index=ASSETS)
    if method == 'naive':
        cov = window_returns.cov().fillna(0.0).to_numpy(dtype=float)
        weights = _markowitz_optimize(sharpe.to_numpy(dtype=float), cov, min_weight=min_weight, max_weight=max_weight)
        return pd.Series(weights, index=ASSETS)

    shrink_mean = float(params.get('shrink_mean', 0.33))
    shrink_corr = float(params.get('shrink_corr', 0.33))
    prior_sharpe = np.full(len(ASSETS), float(sharpe.mean()))
    prior_corr = np.full((len(ASSETS), len(ASSETS)), 0.5)
    np.fill_diagonal(prior_corr, 1.0)
    shrunk_sharpe = (1.0 - shrink_mean) * sharpe.to_numpy(dtype=float) + shrink_mean * prior_sharpe
    shrunk_corr = (1.0 - shrink_corr) * corr.to_numpy(dtype=float) + shrink_corr * prior_corr
    shrunk_cov = np.diag(vols.to_numpy(dtype=float)).dot(shrunk_corr).dot(np.diag(vols.to_numpy(dtype=float)))
    weights = _markowitz_optimize(shrunk_sharpe, shrunk_cov, min_weight=min_weight, max_weight=max_weight)
    return pd.Series(weights, index=ASSETS)


def prepare_portfolio_optimization_data(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    close_df = pd.DataFrame({name: frame['close'] for name, frame in aligned.items()}, index=common_index).dropna()
    aligned = {name: frame.loc[close_df.index].copy() for name, frame in aligned.items()}
    signal_df = aligned['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['month'] = signal_df.index.month
    signal_df['quarter'] = signal_df.index.quarter
    frequency = str(params.get('rebalance_frequency', 'quarterly')).lower()
    if frequency == 'monthly':
        signal_df['rebalance_signal'] = (signal_df['month'] != signal_df['month'].shift(1)).astype(float)
    else:
        signal_df['rebalance_signal'] = (signal_df['quarter'] != signal_df['quarter'].shift(1)).astype(float)
    returns = close_df.pct_change().replace([np.inf, -np.inf], np.nan)
    window_days = int(params.get('window_days', 252 * 5))
    weight_records = []
    valid_dates = []
    method_used = []
    avg_corr_list = []
    for idx in range(len(signal_df)):
        date = signal_df.index[idx]
        if idx < window_days:
            continue
        window_returns = returns.iloc[idx - window_days:idx].dropna()
        if len(window_returns) < max(252, window_days // 2):
            continue
        weights = _compute_weights(window_returns, params)
        weight_records.append(weights)
        valid_dates.append(date)
        method_used.append(str(params.get('method', 'shrinkage')).lower())
        corr_values = window_returns.corr().to_numpy(dtype=float)
        avg_corr_list.append(float(np.nanmean(corr_values[np.triu_indices_from(corr_values, k=1)])))
    weight_df = pd.DataFrame(weight_records, index=valid_dates)
    signal_df = signal_df.loc[weight_df.index].copy()
    for asset in ASSETS:
        signal_df[f'weight_{asset.lower()}'] = weight_df[asset].astype(float)
    signal_df['avg_pair_corr'] = avg_corr_list
    signal_df['method_code'] = np.where(np.array(method_used) == 'shrinkage', 1.0, 0.0)
    aligned = {name: frame.loc[signal_df.index].copy() for name, frame in aligned.items()}
    return aligned, signal_df


class PortfolioOptimizationSignalFeed(bt.feeds.PandasData):
    lines = ('month', 'quarter', 'rebalance_signal', 'weight_xauusd', 'weight_xagusd', 'weight_gdx', 'avg_pair_corr', 'method_code')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month', 6), ('quarter', 7), ('rebalance_signal', 8), ('weight_xauusd', 9), ('weight_xagusd', 10), ('weight_gdx', 11), ('avg_pair_corr', 12), ('method_code', 13),
    )


class PortfolioOptimizationRandomDataGoldStrategy(bt.Strategy):
    params = dict(
        method="shrinkage",
        rebalance_frequency="quarterly",
        window_days=1260,
        shrink_mean=0.33,
        shrink_corr=0.33,
        max_weight=0.6,
        min_weight=0.0,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_map = {name: self.getdatabyname(name) for name in ASSETS}
        self.order_refs = set()
        self.bar_num = 0
        self.rebalance_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.switch_count = 0
        self.last_weights = None
        self.broker_value_series = []

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
        return round(broker_value * float(target_pct) / (price * multiplier), 2)

    def _target_map(self):
        return {
            'XAUUSD': float(self.signal.weight_xauusd[0]),
            'XAGUSD': float(self.signal.weight_xagusd[0]),
            'GDX': float(self.signal.weight_gdx[0]),
        }

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        if float(self.signal.rebalance_signal[0]) <= 0.5:
            return
        targets = self._target_map()
        if self.last_weights is not None and all(abs(targets[k] - self.last_weights.get(k, 0.0)) < 1e-9 for k in targets):
            return
        if self.last_weights is not None:
            self.switch_count += 1
        self.last_weights = dict(targets)
        self.rebalance_count += 1
        for asset_name, data in self.asset_map.items():
            current_size = float(self.getposition(data).size)
            order = self.order_target_size(data=data, target=self._target_size(data, targets[asset_name]))
            self._submit(order)
            if order is not None:
                if targets[asset_name] > 0 and current_size <= 0:
                    self.buy_count += 1
                elif targets[asset_name] <= 0 and current_size > 0:
                    self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)
