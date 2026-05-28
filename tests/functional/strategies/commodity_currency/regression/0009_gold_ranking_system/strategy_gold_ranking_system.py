from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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


def prepare_ranking_frames(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    asset_frames = {symbol: frame.loc[common_index].copy() for symbol, frame in asset_frames.items()}

    ma_days = int(params.get('ma_period_months', 10)) * 21
    momentum_days = int(params.get('momentum_period_months', 3)) * 21

    signal_df = pd.DataFrame(index=common_index)
    signal_df['month'] = signal_df.index.month
    signal_df['rebalance_signal'] = (signal_df['month'] != signal_df['month'].shift(1)).astype(float)

    for symbol, frame in asset_frames.items():
        close = frame['close']
        ma = close.rolling(ma_days).mean()
        momentum = close.pct_change(momentum_days)
        volatility = close.pct_change().rolling(momentum_days).std() * np.sqrt(252)
        risk_adj_momentum = momentum / volatility.replace(0, np.nan)
        signal_df[f'{symbol}_above_ma'] = (close > ma).astype(float)
        signal_df[f'{symbol}_momentum'] = momentum
        signal_df[f'{symbol}_volatility'] = volatility
        signal_df[f'{symbol}_risk_adj_momentum'] = risk_adj_momentum

    return asset_frames, signal_df.dropna()


class GoldRankingSignalFeed(bt.feeds.PandasData):
    lines = (
        'month', 'rebalance_signal',
        'gld_above_ma', 'gld_momentum', 'gld_volatility', 'gld_risk_adj_momentum',
        'iau_above_ma', 'iau_momentum', 'iau_volatility', 'iau_risk_adj_momentum',
        'gdx_above_ma', 'gdx_momentum', 'gdx_volatility', 'gdx_risk_adj_momentum',
        'gdxj_above_ma', 'gdxj_momentum', 'gdxj_volatility', 'gdxj_risk_adj_momentum',
        'bar_above_ma', 'bar_momentum', 'bar_volatility', 'bar_risk_adj_momentum',
    )
    params = (
        ('datetime', None),
        ('month', 0), ('rebalance_signal', 1),
        ('gld_above_ma', 2), ('gld_momentum', 3), ('gld_volatility', 4), ('gld_risk_adj_momentum', 5),
        ('iau_above_ma', 6), ('iau_momentum', 7), ('iau_volatility', 8), ('iau_risk_adj_momentum', 9),
        ('gdx_above_ma', 10), ('gdx_momentum', 11), ('gdx_volatility', 12), ('gdx_risk_adj_momentum', 13),
        ('gdxj_above_ma', 14), ('gdxj_momentum', 15), ('gdxj_volatility', 16), ('gdxj_risk_adj_momentum', 17),
        ('bar_above_ma', 18), ('bar_momentum', 19), ('bar_volatility', 20), ('bar_risk_adj_momentum', 21),
    )


class GoldRankingSystemStrategy(bt.Strategy):
    params = dict(
        n_select=3,
        ma_period_months=10,
        momentum_period_months=3,
        rebalance_frequency='monthly',
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_symbols = ['GLD', 'IAU', 'GDX', 'GDXJ', 'BAR']
        self.asset_map = {symbol: self.getdatabyname(symbol) for symbol in self.asset_symbols}
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_log = []
        self.broker_value_series = []
        self.current_selection = []

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _get_metric(self, symbol, suffix):
        return float(getattr(self.signal, f'{symbol.lower()}_{suffix}')[0])

    def _select_assets(self):
        candidates = []
        for symbol in self.asset_symbols:
            above_ma = self._get_metric(symbol, 'above_ma') > 0.5
            score = self._get_metric(symbol, 'risk_adj_momentum')
            if not above_ma or math.isnan(score):
                continue
            candidates.append((symbol, score))
        candidates.sort(key=lambda item: item[1], reverse=True)
        return [symbol for symbol, _ in candidates[:int(self.p.n_select)]]

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        if float(self.signal.rebalance_signal[0]) <= 0.5:
            return
        selected = self._select_assets()
        target_weight = 1.0 / len(selected) if selected else 0.0
        for symbol, data in self.asset_map.items():
            current_size = float(self.getposition(data).size)
            target = target_weight if symbol in selected else 0.0
            self._submit(self.order_target_percent(data=data, target=target))
            if target > 0 and current_size <= 0:
                self.buy_count += 1
            elif target <= 0 and current_size > 0:
                self.sell_count += 1
        self.current_selection = selected

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append({'pnlcomm': trade.pnlcomm})
