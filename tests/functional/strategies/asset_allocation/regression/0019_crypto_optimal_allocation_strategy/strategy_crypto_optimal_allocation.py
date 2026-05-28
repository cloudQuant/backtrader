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


def prepare_allocation_inputs(asset_map):
    aligned_index = None
    prepared = {}
    for symbol, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    close_df = pd.DataFrame({symbol: frame.loc[aligned_index, 'close'] for symbol, frame in asset_map.items()}, index=aligned_index)
    returns_df = np.log(close_df / close_df.shift(1)).dropna().copy()
    valid_index = returns_df.index
    prepared = {symbol: frame.loc[valid_index].copy() for symbol, frame in prepared.items()}
    return prepared, returns_df


def _optimize_weights(returns_window, params):
    annual_returns = returns_window.mean() * 252.0
    annual_cov = returns_window.cov() * 252.0
    asset_names = list(returns_window.columns)
    base_assets = [name for name in asset_names if name != 'crypto']
    rf = float(params.get('risk_free_rate', 0.02))
    max_crypto = float(params.get('max_crypto_weight', 0.10))
    min_crypto = float(params.get('min_crypto_weight', 0.02))
    step = float(params.get('crypto_grid_step', 0.01))
    vol = returns_window[base_assets].std().replace(0, np.nan)
    inv_vol = 1.0 / vol
    inv_vol = inv_vol.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if inv_vol.sum() <= 0:
        base_w = pd.Series(1.0 / len(base_assets), index=base_assets)
    else:
        base_w = inv_vol / inv_vol.sum()
    best_sharpe = -1e18
    best_weights = None
    grid = np.arange(min_crypto, max_crypto + step / 2.0, step)
    if len(grid) == 0:
        grid = np.array([max_crypto])
    for crypto_w in grid:
        weights = pd.Series(0.0, index=asset_names)
        weights.loc[base_assets] = base_w * max(0.0, 1.0 - crypto_w)
        weights.loc['crypto'] = crypto_w
        port_return = float(np.dot(weights.values, annual_returns.loc[asset_names].values))
        port_var = float(weights.values.T @ annual_cov.loc[asset_names, asset_names].values @ weights.values)
        port_vol = np.sqrt(max(port_var, 1e-12))
        sharpe = (port_return - rf) / port_vol if port_vol > 0 else -1e18
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_weights = weights.copy()
    return best_weights.to_dict() if best_weights is not None else {name: 1.0 / len(asset_names) for name in asset_names}


class CryptoOptimalAllocationStrategy(bt.Strategy):
    params = dict(
        rebalance_interval_days=21,
        weight_lookup=None,
        lookback_days=63,
        risk_free_rate=0.02,
        min_weight=0.0,
        max_crypto_weight=0.1,
        min_crypto_weight=0.02,
        crypto_grid_step=0.01,
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
        self.crypto_weight_sum = 0.0

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
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        weights = (self.p.weight_lookup or {}).get(current_dt)
        if weights is None:
            return
        self.rebalance_count += 1
        self.crypto_weight_sum += float(weights.get('crypto', 0.0))
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
