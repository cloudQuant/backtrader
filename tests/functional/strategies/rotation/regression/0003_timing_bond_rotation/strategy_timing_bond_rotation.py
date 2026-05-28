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


def prepare_timing_bond_rotation_inputs(asset_map, params):
    aligned_index = None
    prepared = {}
    for symbol, df in asset_map.items():
        frame = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy().sort_index()
        prepared[symbol] = frame
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    if aligned_index is None or len(aligned_index) == 0:
        raise ValueError('No overlapping data available for timing bond rotation strategy')
    aligned_index = aligned_index.sort_values()
    prepared = {symbol: frame.loc[aligned_index].copy() for symbol, frame in prepared.items()}
    close_df = pd.concat(
        [frame[['close']].rename(columns={'close': symbol}) for symbol, frame in prepared.items()],
        axis=1,
    ).dropna(how='any')
    aligned_index = close_df.index
    prepared = {symbol: frame.loc[aligned_index].copy() for symbol, frame in prepared.items()}

    ma_period = int(params.get('ma_period', 200))
    r1 = int(params.get('momentum_1m', 21))
    r3 = int(params.get('momentum_3m', 63))
    r6 = int(params.get('momentum_6m', 126))
    r12 = int(params.get('momentum_12m', 252))
    weights = params.get('momentum_weights', {}) or {}
    w1 = float(weights.get('r1m', 12.0))
    w3 = float(weights.get('r3m', 4.0))
    w6 = float(weights.get('r6m', 2.0))
    w12 = float(weights.get('r12m', 1.0))

    equity_close = close_df['equity']
    ma200 = equity_close.rolling(ma_period).mean()
    bullish = (equity_close > ma200).astype(float)

    bond_symbols = [symbol for symbol in close_df.columns if symbol != 'equity']
    momentum_scores = pd.DataFrame(index=close_df.index)
    for symbol in bond_symbols:
        prices = close_df[symbol]
        momentum_scores[symbol] = (
            w1 * prices.pct_change(r1) +
            w3 * prices.pct_change(r3) +
            w6 * prices.pct_change(r6) +
            w12 * prices.pct_change(r12)
        ) / 4.0

    valid_rows = momentum_scores.notna().any(axis=1) & ma200.notna()
    momentum_scores = momentum_scores.loc[valid_rows].copy()
    bullish = bullish.loc[valid_rows].copy()
    ma200 = ma200.loc[valid_rows].copy()
    best_bond = momentum_scores.idxmax(axis=1)
    best_bond_momentum = momentum_scores.max(axis=1)

    signal_df = pd.DataFrame(index=momentum_scores.index)
    signal_df['equity_above_ma'] = bullish
    signal_df['equity_ma200'] = ma200
    signal_df['best_bond'] = best_bond
    signal_df['best_bond_momentum'] = best_bond_momentum
    signal_df['target_asset'] = signal_df['best_bond']
    signal_df.loc[signal_df['equity_above_ma'] > 0.5, 'target_asset'] = 'equity'
    for symbol in bond_symbols:
        signal_df[f'{symbol}_momentum'] = momentum_scores[symbol]

    prepared = {symbol: frame.loc[signal_df.index].copy() for symbol, frame in prepared.items()}
    return prepared, signal_df, signal_df.index


class TimingBondRotationStrategy(bt.Strategy):
    params = dict(
        signal_lookup=None,
        rebalance_interval_days=21,
        rebalance_threshold=0.05,
        position_size=0.95,
        ma_period=200,
        momentum_1m=21,
        momentum_3m=63,
        momentum_6m=126,
        momentum_12m=252,
        momentum_weights={'r1m': 12.0, 'r3m': 4.0, 'r6m': 2.0, 'r12m': 1.0},
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.rebalance_count = 0
        self.pending_orders = []
        self.current_asset = None
        self.broker_value_series = []
        self.signal_lookup = self.p.signal_lookup or {}
        self.data_by_name = {data._name: data for data in self.datas}

    def _portfolio_weights(self):
        portfolio_value = float(self.broker.getvalue())
        if portfolio_value <= 0:
            return {name: 0.0 for name in self.data_by_name}
        weights = {}
        for name, data in self.data_by_name.items():
            position = self.getposition(data)
            weights[name] = float(position.size) * float(data.close[0]) / portfolio_value if position.size else 0.0
        return weights

    def _rebalance_to(self, target_asset):
        weights = self._portfolio_weights()
        for name, data in self.data_by_name.items():
            target = float(self.p.position_size) if name == target_asset else 0.0
            current = weights.get(name, 0.0)
            if target > current:
                self.buy_count += 1
            elif current > 0 and target < current:
                self.sell_count += 1
            order = self.order_target_percent(data=data, target=target)
            if order is not None:
                self.pending_orders.append(order)
        self.current_asset = target_asset
        self.rebalance_count += 1

    def next(self):
        self.bar_num += 1
        current_dt = bt.num2date(self.datas[0].datetime[0]).replace(tzinfo=None)
        self.broker_value_series.append((current_dt, float(self.broker.getvalue())))
        if self.pending_orders:
            return
        if self.bar_num != 1 and self.bar_num % int(self.p.rebalance_interval_days) != 0:
            return
        signal = self.signal_lookup.get(pd.Timestamp(current_dt))
        if signal is None:
            signal = self.signal_lookup.get(pd.Timestamp(current_dt.date()))
        if signal is None:
            return
        target_asset = str(signal.get('target_asset', 'equity'))
        weights = self._portfolio_weights()
        if self.current_asset != target_asset or weights.get(target_asset, 0.0) < (float(self.p.position_size) - float(self.p.rebalance_threshold)):
            self._rebalance_to(target_asset)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [pending for pending in self.pending_orders if pending is not None and pending.ref != order.ref]
