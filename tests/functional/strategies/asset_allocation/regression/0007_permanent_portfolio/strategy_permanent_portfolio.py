from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


ASSET_ORDER = ['GLD', 'IVV', 'IEF']


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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


def align_asset_frames(asset_frames):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    return {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}


class PermanentPortfolioStrategy(bt.Strategy):
    params = dict(
        target_weights=None,
        cash_weight=0.25,
        rebalance_threshold=0.05,
        gold_rebalance_threshold=0.02,
        lot_size=1.0,
    )

    def __init__(self):
        self.asset_map = {name: self.getdatabyname(name) for name in ASSET_ORDER}
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.rebalance_count = 0
        self.threshold_rebalance_count = 0
        self.last_rebalance_year = None
        self.broker_value_series = []

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _target_size(self, data, target_weight):
        broker_value = float(self.broker.getvalue())
        price = float(data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        return round(broker_value * float(self.p.lot_size) * float(target_weight) / (price * multiplier), 2)

    def _current_weights(self):
        broker_value = float(self.broker.getvalue())
        if broker_value <= 0:
            return {name: 0.0 for name in ASSET_ORDER}
        weights = {}
        for name, data in self.asset_map.items():
            pos = self.getposition(data)
            weights[name] = float(pos.size) * float(data.close[0]) / broker_value
        return weights

    def _needs_threshold_rebalance(self):
        current_weights = self._current_weights()
        target_weights = self.p.target_weights or {}
        for name, target in target_weights.items():
            diff = abs(current_weights.get(name, 0.0) - float(target))
            threshold = float(self.p.gold_rebalance_threshold) if name == 'GLD' else float(self.p.rebalance_threshold)
            if diff > threshold:
                return True
        return False

    def _rebalance(self):
        target_weights = self.p.target_weights or {}
        for name, data in self.asset_map.items():
            target_weight = float(target_weights.get(name, 0.0))
            current_size = float(self.getposition(data).size)
            target_size = self._target_size(data, target_weight)
            order = self.order_target_size(data=data, target=target_size)
            self._submit(order)
            if order is not None:
                if target_size > current_size:
                    self.buy_count += 1
                elif target_size < current_size:
                    self.sell_count += 1
        self.rebalance_count += 1
        self.last_rebalance_year = bt.num2date(self.datas[0].datetime[0]).year

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.datas[0].datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        current_date = bt.num2date(self.datas[0].datetime[0])
        current_year = current_date.year
        if self.last_rebalance_year is None:
            self._rebalance()
            return
        if current_year != self.last_rebalance_year:
            self._rebalance()
            return
        if self._needs_threshold_rebalance():
            self.threshold_rebalance_count += 1
            self._rebalance()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)
