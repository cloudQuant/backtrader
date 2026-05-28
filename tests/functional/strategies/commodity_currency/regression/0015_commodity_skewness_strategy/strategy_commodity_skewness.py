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


def prepare_skewness_data(price_map, params):
    aligned_index = None
    prepared = {}
    skewness_lookback = int(params.get('skewness_lookback', 126))
    for symbol, frame in price_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in price_map.items():
        px = frame.loc[aligned_index].copy()
        price_ratio = (px['close'] / px['close'].shift(1)).replace([np.inf, -np.inf], np.nan)
        price_ratio = price_ratio.where(price_ratio > 0)
        log_returns = np.log(price_ratio)
        skewness = log_returns.rolling(skewness_lookback).skew()
        prepared[symbol] = px[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
        prepared[symbol]['skewness'] = skewness.astype(float)
    score_df = pd.DataFrame({symbol: frame['skewness'] for symbol, frame in prepared.items()}, index=aligned_index)
    return prepared, score_df.dropna(how='all')


class CommoditySkewnessFeed(bt.feeds.PandasData):
    lines = ('skewness',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('skewness', 6),
    )


class CommoditySkewnessStrategy(bt.Strategy):
    params = dict(
        n_long=2,
        n_short=2,
        rebalance_interval_days=21,
        max_leg_notional_pct=0.25,
        skewness_lookback=126,
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
        self.long_books = 0
        self.short_books = 0

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
        self.broker_value_series.append((bt.num2date(self.datas[0].datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        skews = []
        for data in self.datas:
            skew = float(data.skewness[0]) if data.skewness[0] == data.skewness[0] else None
            if skew is None:
                continue
            skews.append((data, skew))
        if len(skews) < max(int(self.p.n_long), int(self.p.n_short)):
            return
        ranked = sorted(skews, key=lambda item: item[1])
        long_group = ranked[:int(self.p.n_long)]
        short_group = ranked[-int(self.p.n_short):]
        target_map = {data._name: 0.0 for data in self.datas}
        long_weight = float(self.p.max_leg_notional_pct) / max(1, int(self.p.n_long))
        short_weight = -float(self.p.max_leg_notional_pct) / max(1, int(self.p.n_short))
        for data, _ in long_group:
            target_map[data._name] = long_weight
        for data, _ in short_group:
            target_map[data._name] = short_weight
        self.long_books += 1
        self.short_books += 1
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
