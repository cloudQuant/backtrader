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
    return prepared, close_df, aligned_index


def build_weight_lookup(close_df, params):
    sma_period = int(params.get('sma_period', 200))
    vol_lookback = int(params.get('vol_lookback', 60))
    rebalance_step = max(1, int(params.get('rebalance_interval_days', 21)))
    base_gold = float(params.get('base_gold_weight', 0.05))
    min_gold = float(params.get('min_gold_weight', 0.0))
    max_gold = float(params.get('max_gold_weight', 0.15))
    trend_weight = float(params.get('trend_weight', 0.5))
    volatility_weight = float(params.get('volatility_weight', 0.3))
    economic_weight = float(params.get('economic_weight', 0.2))
    weight_lookup = {}
    returns = close_df.pct_change()
    for idx in range(max(sma_period, vol_lookback) + 1, len(close_df), rebalance_step):
        date = pd.Timestamp(close_df.index[idx]).tz_localize(None)
        equity_series = close_df['equity'].iloc[: idx + 1]
        commodity_series = close_df['commodity'].iloc[: idx + 1]
        equity_price = float(equity_series.iloc[-1])
        sma = float(equity_series.iloc[-sma_period:].mean())
        trend_signal = 1.0 if equity_price < sma else -1.0
        realized_vol = float(returns['equity'].iloc[idx - vol_lookback:idx].std() * np.sqrt(252)) if idx >= vol_lookback else 0.0
        volatility_signal = 1.0 if realized_vol > 0.2 else (-1.0 if realized_vol < 0.1 else 0.0)
        commodity_momentum = float(commodity_series.iloc[-1] / commodity_series.iloc[-vol_lookback] - 1.0)
        economic_signal = 1.0 if commodity_momentum > 0 else -1.0
        composite = trend_signal * trend_weight + volatility_signal * volatility_weight + economic_signal * economic_weight
        gold_weight = base_gold + composite * 0.05
        gold_weight = max(min_gold, min(max_gold, gold_weight))
        remaining = max(0.0, 1.0 - gold_weight)
        equity_weight = remaining * 0.6
        bond_weight = remaining * 0.4
        weight_lookup[date] = {'equity': equity_weight, 'bond': bond_weight, 'gold': gold_weight, 'commodity': 0.0}
    return weight_lookup


class OptimalGoldAllocationStrategy(bt.Strategy):
    params = dict(
        weight_lookup=None,
        rebalance_interval_days=21,
        base_gold_weight=0.05,
        max_gold_weight=0.15,
        min_gold_weight=0.0,
        trend_weight=0.5,
        volatility_weight=0.3,
        economic_weight=0.2,
        sma_period=200,
        vol_lookback=60,
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
        self.gold_weight_series = []

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
        self.gold_weight_series.append(float(weights.get('gold', 0.0)))
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
