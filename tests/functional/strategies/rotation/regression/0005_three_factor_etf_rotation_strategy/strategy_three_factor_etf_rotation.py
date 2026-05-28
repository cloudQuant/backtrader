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


def prepare_rotation_inputs(asset_map, params):
    aligned_index = None
    prepared = {}
    for symbol, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    close_df = pd.DataFrame({symbol: frame.loc[aligned_index, 'close'] for symbol, frame in asset_map.items()}, index=aligned_index)
    lb3 = int(params.get('lookback_3m', 63))
    lb20 = int(params.get('lookback_20d', 20))
    ranking_lookup = {}
    for idx in range(max(lb3, lb20) + 1, len(close_df)):
        date = pd.Timestamp(close_df.index[idx]).tz_localize(None)
        rows = []
        for symbol in close_df.columns:
            series = close_df[symbol].iloc[: idx + 1].dropna()
            ret_3m = float(series.iloc[-1] / series.iloc[-lb3] - 1.0)
            ret_20d = float(series.iloc[-1] / series.iloc[-lb20] - 1.0)
            log_ret = np.log(series / series.shift(1)).dropna()
            vol_20d = float(log_ret.iloc[-lb20:].std() * np.sqrt(252))
            rows.append({'symbol': symbol, 'ret_3m': ret_3m, 'ret_20d': ret_20d, 'vol_20d': vol_20d})
        factor_df = pd.DataFrame(rows)
        factor_df['rank_3m'] = factor_df['ret_3m'].rank(method='first', ascending=False)
        factor_df['rank_20d'] = factor_df['ret_20d'].rank(method='first', ascending=False)
        factor_df['rank_vol'] = factor_df['vol_20d'].rank(method='first', ascending=True)
        factor_df['frv'] = (
            factor_df['rank_3m'] * float(params.get('weight_3m', 0.4)) +
            factor_df['rank_20d'] * float(params.get('weight_20d', 0.4)) +
            factor_df['rank_vol'] * float(params.get('weight_vol', 0.2))
        )
        ranking_lookup[date] = factor_df.sort_values('frv').reset_index(drop=True)
    return prepared, ranking_lookup, aligned_index


class ThreeFactorETFRotationStrategy(bt.Strategy):
    params = dict(
        top_n=3,
        rebalance_interval_days=21,
        ranking_lookup=None,
        lookback_3m=63,
        lookback_20d=20,
        weight_3m=0.4,
        weight_20d=0.4,
        weight_vol=0.2,
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
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        ranking = (self.p.ranking_lookup or {}).get(current_dt)
        if ranking is None or ranking.empty:
            return
        selected = set(ranking.head(max(1, int(self.p.top_n)))['symbol'].tolist())
        target_weight = 1.0 / len(selected) if selected else 0.0
        self.rebalance_count += 1
        for data in self.datas:
            target_pct = target_weight if data._name in selected else 0.0
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
