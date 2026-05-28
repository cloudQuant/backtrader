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


def prepare_regime_inputs(asset_map, params):
    aligned_index = None
    prepared = {}
    for symbol, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    close_df = pd.DataFrame({symbol: frame.loc[aligned_index, 'close'] for symbol, frame in asset_map.items()}, index=aligned_index)
    returns_df = np.log(close_df / close_df.shift(1)).dropna()
    window = int(params.get('correlation_window', 60))
    corr_df = pd.DataFrame(index=returns_df.index)
    corr_df['equity_bond_corr'] = returns_df['equity'].rolling(window).corr(returns_df['bond'])
    corr_df['equity_gold_corr'] = returns_df['equity'].rolling(window).corr(returns_df['gold'])
    corr_df['equity_commodity_corr'] = returns_df['equity'].rolling(window).corr(returns_df['commodity'])
    corr_df = corr_df.replace([np.inf, -np.inf], np.nan).dropna().copy()
    valid_index = corr_df.index
    prepared = {symbol: frame.loc[valid_index].copy() for symbol, frame in prepared.items()}
    return prepared, corr_df


class CorrelationRegimeStrategy(bt.Strategy):
    params = dict(
        risk_on_threshold=-0.3,
        risk_off_threshold=0.0,
        rebalance_interval_days=21,
        allocation=None,
        correlation_lookup=None,
        correlation_window=60,
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
        self.risk_on_days = 0
        self.risk_off_days = 0
        self.neutral_days = 0

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
        corr = (self.p.correlation_lookup or {}).get(current_dt)
        if corr is None:
            return
        equity_bond_corr = float(corr['equity_bond_corr'])
        if equity_bond_corr < float(self.p.risk_on_threshold):
            regime = 'risk_on'
            self.risk_on_days += 1
        elif equity_bond_corr > float(self.p.risk_off_threshold):
            regime = 'risk_off'
            self.risk_off_days += 1
        else:
            regime = 'neutral'
            self.neutral_days += 1
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        allocation = (self.p.allocation or {}).get(regime, {})
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
