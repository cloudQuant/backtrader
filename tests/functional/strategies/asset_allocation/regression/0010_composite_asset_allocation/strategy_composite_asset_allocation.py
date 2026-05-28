from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd

ASSET_NAMES = ['ivv', 'efa', 'bil', 'ief', 'gtip']
TRADED_NAMES = ['ivv', 'efa', 'ief']


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


def prepare_composite_allocation_inputs(asset_map, params):
    aligned_index = None
    prepared = {}
    for symbol, df in asset_map.items():
        frame = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy().sort_index()
        prepared[symbol] = frame
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    if aligned_index is None or len(aligned_index) == 0:
        raise ValueError('No overlapping data available for composite asset allocation strategy')
    aligned_index = aligned_index.sort_values()
    prepared = {symbol: frame.loc[aligned_index].copy() for symbol, frame in prepared.items()}

    close_df = pd.concat([prepared[name][['close']].rename(columns={'close': name}) for name in ASSET_NAMES], axis=1).dropna(how='any')
    aligned_index = close_df.index
    prepared = {symbol: frame.loc[aligned_index].copy() for symbol, frame in prepared.items()}

    periods_months = [int(value) for value in params.get('momentum_periods_months', [3, 6, 9, 12, 15])]
    periods_days = [month * 21 for month in periods_months]
    macro_lookback = int(params.get('macro_lookback_months', 6)) * 21

    momentum = pd.DataFrame(index=close_df.index)
    for symbol in ('ivv', 'efa', 'bil', 'ief'):
        components = [close_df[symbol].pct_change(period) for period in periods_days]
        momentum[symbol] = pd.concat(components, axis=1).mean(axis=1)

    macro_score = pd.DataFrame(index=close_df.index)
    macro_score['equity_trend'] = close_df['ivv'].pct_change(macro_lookback)
    macro_score['inflation_trend'] = close_df['gtip'].pct_change(macro_lookback)
    macro_score['bond_trend'] = close_df['ief'].pct_change(macro_lookback)
    macro_score['score'] = 0.0
    macro_score.loc[macro_score['equity_trend'] > 0, 'score'] += 1.0
    macro_score.loc[macro_score['inflation_trend'] > 0, 'score'] += 1.0
    macro_score.loc[macro_score['bond_trend'] < 0, 'score'] += 1.0

    valid_rows = momentum.notna().all(axis=1) & macro_score[['equity_trend', 'inflation_trend', 'bond_trend']].notna().all(axis=1)
    momentum = momentum.loc[valid_rows].copy()
    macro_score = macro_score.loc[valid_rows].copy()
    close_df = close_df.loc[valid_rows].copy()
    prepared = {symbol: frame.loc[close_df.index].copy() for symbol, frame in prepared.items()}

    equity_relative = pd.concat([momentum['ivv'].rename('ivv'), momentum['efa'].rename('efa')], axis=1)
    trend_winner = equity_relative.idxmax(axis=1)
    trend_winner_momentum = equity_relative.max(axis=1)
    trend_asset = trend_winner.where(trend_winner_momentum > momentum['bil'], 'ief')
    macro_asset = pd.Series('ief', index=close_df.index)
    macro_asset.loc[macro_score['score'] >= 2.0] = 'ivv'

    signal_df = pd.DataFrame(index=close_df.index)
    signal_df['trend_asset'] = trend_asset
    signal_df['macro_asset'] = macro_asset
    signal_df['trend_weight'] = float(params.get('trend_following_weight', 0.25))
    signal_df['macro_weight'] = float(params.get('macro_economic_weight', 0.25))
    signal_df['passive_equity_weight'] = float(params.get('passive_equity_weight', 0.25))
    signal_df['passive_bond_weight'] = float(params.get('passive_bond_weight', 0.25))
    signal_df['ivv_target'] = signal_df['passive_equity_weight']
    signal_df['efa_target'] = 0.0
    signal_df['ief_target'] = signal_df['passive_bond_weight']
    signal_df.loc[signal_df['trend_asset'] == 'ivv', 'ivv_target'] += signal_df['trend_weight']
    signal_df.loc[signal_df['trend_asset'] == 'efa', 'efa_target'] += signal_df['trend_weight']
    signal_df.loc[signal_df['trend_asset'] == 'ief', 'ief_target'] += signal_df['trend_weight']
    signal_df.loc[signal_df['macro_asset'] == 'ivv', 'ivv_target'] += signal_df['macro_weight']
    signal_df.loc[signal_df['macro_asset'] == 'ief', 'ief_target'] += signal_df['macro_weight']
    signal_df['trend_winner_momentum'] = trend_winner_momentum
    signal_df['bil_momentum'] = momentum['bil']
    signal_df['macro_score'] = macro_score['score']
    signal_df['total_target'] = signal_df['ivv_target'] + signal_df['efa_target'] + signal_df['ief_target']
    return prepared, signal_df, signal_df.index


class CompositeAssetAllocationStrategy(bt.Strategy):
    params = dict(
        signal_lookup=None,
        rebalance_interval_days=21,
        rebalance_threshold=0.05,
        trend_following_weight=0.25,
        macro_economic_weight=0.25,
        passive_equity_weight=0.25,
        passive_bond_weight=0.25,
        momentum_periods_months=[3, 6, 9, 12, 15],
        macro_lookback_months=6,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.rebalance_count = 0
        self.pending_orders = []
        self.broker_value_series = []
        self.signal_lookup = self.p.signal_lookup or {}
        self.data_by_name = {data._name: data for data in self.datas}

    def _portfolio_weights(self):
        portfolio_value = float(self.broker.getvalue())
        if portfolio_value <= 0:
            return {name: 0.0 for name in TRADED_NAMES}
        weights = {}
        for name in TRADED_NAMES:
            data = self.data_by_name[name]
            position = self.getposition(data)
            weights[name] = float(position.size) * float(data.close[0]) / portfolio_value if position.size else 0.0
        return weights

    def _rebalance(self, targets):
        current_weights = self._portfolio_weights()
        for name in TRADED_NAMES:
            data = self.data_by_name[name]
            target = float(targets.get(name, 0.0))
            current = current_weights.get(name, 0.0)
            if target > current:
                self.buy_count += 1
            elif current > 0 and target < current:
                self.sell_count += 1
            order = self.order_target_percent(data=data, target=target)
            if order is not None:
                self.pending_orders.append(order)
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
        targets = {
            'ivv': float(signal.get('ivv_target', 0.0)),
            'efa': float(signal.get('efa_target', 0.0)),
            'ief': float(signal.get('ief_target', 0.0)),
        }
        current_weights = self._portfolio_weights()
        if any(abs(current_weights.get(name, 0.0) - targets.get(name, 0.0)) > float(self.p.rebalance_threshold) for name in TRADED_NAMES):
            self._rebalance(targets)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [pending for pending in self.pending_orders if pending is not None and pending.ref != order.ref]
