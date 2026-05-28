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


def prepare_asset_data(price_map):
    aligned_index = None
    prepared = {}
    for symbol, frame in price_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in price_map.items():
        prepared[symbol] = frame.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    return prepared, aligned_index


class AdaptiveAllocationStrategy(bt.Strategy):
    params = dict(
        momentum_lookback=126,
        volatility_lookback=63,
        n_select=3,
        rebalance_interval_days=21,
        max_asset_weight=0.6,
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
        self.selected_asset_days = {data._name: 0 for data in self.datas}

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

    def _compute_momentum(self, data):
        if len(data) <= int(self.p.momentum_lookback):
            return None
        prev_close = float(data.close[-int(self.p.momentum_lookback)])
        current_close = float(data.close[0])
        if prev_close <= 0:
            return None
        return current_close / prev_close - 1.0

    def _compute_vol(self, data):
        if len(data) <= int(self.p.volatility_lookback):
            return None
        prices = [float(data.close[-idx]) for idx in range(int(self.p.volatility_lookback), -1, -1)]
        returns = pd.Series(prices).pct_change().dropna()
        if returns.empty:
            return None
        vol = float(returns.std()) * (252 ** 0.5)
        return vol if vol > 0 else None

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.datas[0].datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        ranked = []
        for data in self.datas:
            momentum = self._compute_momentum(data)
            vol = self._compute_vol(data)
            if momentum is None or vol is None:
                continue
            ranked.append((data, momentum, vol))
        ranked = [item for item in ranked if item[1] > 0]
        ranked.sort(key=lambda item: item[1], reverse=True)
        selected = ranked[:int(self.p.n_select)]
        inv_vol_sum = sum(1.0 / item[2] for item in selected) if selected else 0.0
        target_map = {data._name: 0.0 for data in self.datas}
        for data, _, vol in selected:
            raw_weight = (1.0 / vol) / inv_vol_sum if inv_vol_sum > 0 else 0.0
            target_map[data._name] = min(float(self.p.max_asset_weight), raw_weight)
            self.selected_asset_days[data._name] += 1
        total_weight = sum(target_map.values())
        if total_weight > 1.0 and total_weight > 0:
            target_map = {key: value / total_weight for key, value in target_map.items()}
        self.rebalance_count += 1
        for data in self.datas:
            target_pct = target_map[data._name]
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
