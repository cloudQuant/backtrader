from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
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


def _build_leveraged_bond_frame(base_df, leverage_multiple):
    frame = base_df.copy()
    returns = frame['close'].pct_change().fillna(0.0)
    leveraged_nav = (1.0 + returns * float(leverage_multiple)).clip(lower=0.05).cumprod() * 100.0
    out = pd.DataFrame(index=frame.index)
    out['close'] = leveraged_nav
    out['open'] = out['close'].shift(1).fillna(out['close'])
    out['high'] = out[['open', 'close']].max(axis=1)
    out['low'] = out[['open', 'close']].min(axis=1)
    out['volume'] = frame['volume'].fillna(0.0)
    out['openinterest'] = 0.0
    return out[['open', 'high', 'low', 'close', 'volume', 'openinterest']]


def prepare_bond_risk_premium_inputs(asset_map, params):
    aligned_index = None
    prepared = {}
    for symbol, df in asset_map.items():
        frame = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy().sort_index()
        prepared[symbol] = frame
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    if aligned_index is None or len(aligned_index) == 0:
        raise ValueError('No overlapping data available for bond risk premium strategy')
    aligned_index = aligned_index.sort_values()
    prepared = {symbol: frame.loc[aligned_index].copy() for symbol, frame in prepared.items()}
    prepared['bond_leveraged'] = _build_leveraged_bond_frame(prepared['bond_base'], params.get('leverage_multiple', 3.0)).loc[aligned_index].copy()
    close_df = pd.concat([
        prepared['equity'][['close']].rename(columns={'close': 'equity'}),
        prepared['bond_leveraged'][['close']].rename(columns={'close': 'bond_leveraged'}),
    ], axis=1).dropna(how='any')
    aligned_index = close_df.index
    prepared = {
        'equity': prepared['equity'].loc[aligned_index].copy(),
        'bond_leveraged': prepared['bond_leveraged'].loc[aligned_index].copy(),
    }
    return prepared, close_df, aligned_index


class BondRiskPremiumStrategy(bt.Strategy):
    params = dict(
        equity_weight=1.0,
        bond_weight=0.30,
        rebalance_interval_days=21,
        rebalance_threshold=0.05,
        max_drawdown=0.20,
        drawdown_risk_scale=0.50,
        leverage_multiple=3.0,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.rebalance_count = 0
        self.pending_orders = []
        self.broker_value_series = []
        self.peak_value = float(self.broker.getvalue())
        self.data_by_name = {data._name: data for data in self.datas}

    def _current_weights(self):
        portfolio_value = float(self.broker.getvalue())
        if portfolio_value <= 0:
            return {'equity': 0.0, 'bond_leveraged': 0.0}
        weights = {}
        for name, data in self.data_by_name.items():
            position = self.getposition(data)
            weights[name] = float(position.size) * float(data.close[0]) / portfolio_value if position.size else 0.0
        return weights

    def _target_weights(self):
        current_value = float(self.broker.getvalue())
        self.peak_value = max(self.peak_value, current_value)
        drawdown = (self.peak_value - current_value) / self.peak_value if self.peak_value > 0 else 0.0
        scale = 1.0 if drawdown <= float(self.p.max_drawdown) else float(self.p.drawdown_risk_scale)
        return {
            'equity': float(self.p.equity_weight) * scale,
            'bond_leveraged': float(self.p.bond_weight) * scale,
        }

    def _needs_rebalance(self, target_weights):
        current_weights = self._current_weights()
        for name, target in target_weights.items():
            if abs(current_weights.get(name, 0.0) - target) > float(self.p.rebalance_threshold):
                return True
        return False

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.datas[0].datetime[0]), float(self.broker.getvalue())))
        if self.pending_orders:
            return
        if self.bar_num == 1 or self.bar_num % int(self.p.rebalance_interval_days) == 0:
            target_weights = self._target_weights()
            if self.bar_num == 1 or self._needs_rebalance(target_weights):
                current_weights = self._current_weights()
                for name, target in target_weights.items():
                    data = self.data_by_name[name]
                    current_weight = current_weights.get(name, 0.0)
                    if target > current_weight:
                        self.buy_count += 1
                    elif target < current_weight and current_weight > 0:
                        self.sell_count += 1
                    order = self.order_target_percent(data=data, target=target)
                    if order is not None:
                        self.pending_orders.append(order)
                self.rebalance_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [pending for pending in self.pending_orders if pending is not None and pending.ref != order.ref]
