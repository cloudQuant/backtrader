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


def prepare_allocation_inputs(asset_map, params):
    aligned_index = None
    prepared = {}
    for symbol, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    close_df = pd.DataFrame({symbol: frame.loc[aligned_index, 'close'] for symbol, frame in asset_map.items()}, index=aligned_index)
    equity_ret = np.log(close_df['equity'] / close_df['equity'].shift(1))
    realized_vol = equity_ret.rolling(int(params.get('vol_window', 20))).std() * np.sqrt(252)
    vol_df = pd.DataFrame({'realized_vol': realized_vol}, index=aligned_index).dropna().copy()
    valid_index = vol_df.index
    prepared = {symbol: frame.loc[valid_index].copy() for symbol, frame in prepared.items()}
    return prepared, vol_df


class VolatilityBasedAllocationStrategy(bt.Strategy):
    params = dict(
        low_vol=0.15,
        high_vol=0.25,
        extreme_vol=0.35,
        base_equity=0.60,
        min_equity=0.20,
        max_equity=1.00,
        low_vix_factor=1.2,
        normal_vix_factor=1.0,
        high_vix_factor=0.8,
        extreme_vix_factor=0.6,
        rebalance_interval_days=21,
        gold_share_of_defense=0.25,
        vol_lookup=None,
        vol_window=20,
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
        self.low_vol_days = 0
        self.normal_vol_days = 0
        self.high_vol_days = 0
        self.extreme_vol_days = 0

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

    def _weights_from_vol(self, vol):
        if vol < float(self.p.low_vol):
            factor = float(self.p.low_vix_factor)
            self.low_vol_days += 1
        elif vol < float(self.p.high_vol):
            factor = float(self.p.normal_vix_factor)
            self.normal_vol_days += 1
        elif vol < float(self.p.extreme_vol):
            factor = float(self.p.high_vix_factor)
            self.high_vol_days += 1
        else:
            factor = float(self.p.extreme_vix_factor)
            self.extreme_vol_days += 1
        equity_weight = min(float(self.p.max_equity), max(float(self.p.min_equity), float(self.p.base_equity) * factor))
        defense = max(0.0, 1.0 - equity_weight)
        gold_weight = defense * float(self.p.gold_share_of_defense)
        bond_weight = defense - gold_weight
        return equity_weight, bond_weight, gold_weight

    def next(self):
        self.bar_num += 1
        current_dt = pd.Timestamp(bt.num2date(self.datas[0].datetime[0])).tz_localize(None)
        self.broker_value_series.append((bt.num2date(self.datas[0].datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        vol = (self.p.vol_lookup or {}).get(current_dt)
        if vol is None:
            return
        equity_weight, bond_weight, gold_weight = self._weights_from_vol(float(vol))
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        allocation = {'equity': equity_weight, 'bond': bond_weight, 'gold': gold_weight}
        for data in self.datas:
            target_pct = float(allocation.get(data._name, 0.0))
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
