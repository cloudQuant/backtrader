from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSET_NAMES = ['ivv3x', 'xau3x']


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


def build_leveraged_proxy(df, leverage):
    out = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    close_ret = out['close'].pct_change().fillna(0.0)
    proxy_close = 100.0 * (1.0 + leverage * close_ret).clip(lower=-0.95).cumprod()
    prev_close = proxy_close.shift(1).fillna(proxy_close.iloc[0])
    open_ret = (out['open'] / out['close'].shift(1) - 1.0).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    high_ret = (out['high'] / out['close'].shift(1) - 1.0).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    low_ret = (out['low'] / out['close'].shift(1) - 1.0).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    proxy_open = prev_close * (1.0 + leverage * open_ret).clip(lower=-0.95)
    proxy_high = prev_close * (1.0 + leverage * high_ret).clip(lower=-0.95)
    proxy_low = prev_close * (1.0 + leverage * low_ret).clip(lower=-0.95)
    out['open'] = proxy_open
    out['high'] = pd.concat([proxy_open, proxy_close, proxy_high], axis=1).max(axis=1)
    out['low'] = pd.concat([proxy_open, proxy_close, proxy_low], axis=1).min(axis=1)
    out['close'] = proxy_close
    return out.dropna()


def prepare_dual_asset_inputs(asset_map, params):
    ivv = build_leveraged_proxy(asset_map['ivv'], float(params.get('ivv_leverage', 3.0)))
    xau = build_leveraged_proxy(asset_map['xauusd'], float(params.get('xauusd_leverage', 3.0)))
    aligned_index = ivv.index.intersection(xau.index).sort_values()
    ivv = ivv.loc[aligned_index].copy()
    xau = xau.loc[aligned_index].copy()

    close_df = pd.DataFrame({'ivv3x': ivv['close'], 'xau3x': xau['close']}, index=aligned_index).dropna()
    aligned_index = close_df.index
    ivv = ivv.loc[aligned_index].copy()
    xau = xau.loc[aligned_index].copy()

    returns = close_df.pct_change()
    vol = returns.rolling(63, min_periods=20).std() * np.sqrt(252.0)
    corr = returns['ivv3x'].rolling(63, min_periods=20).corr(returns['xau3x'])
    ivv_vol = vol['ivv3x']
    xau_vol = vol['xau3x']
    risk_parity_ivv = xau_vol / (ivv_vol + xau_vol)
    risk_parity_xau = ivv_vol / (ivv_vol + xau_vol)

    crisis_threshold = float(params.get('crisis_vol_threshold', 0.30))
    crisis_ivv_weight = float(params.get('crisis_equity_weight', 0.20))
    crisis_xau_weight = float(params.get('crisis_gold_weight', 0.80))
    reduced_total_exposure = float(params.get('reduced_total_exposure', 0.50))
    max_drawdown_limit = float(params.get('max_drawdown_limit', 0.20))

    rolling_peak = close_df['ivv3x'].cummax()
    ivv_drawdown = close_df['ivv3x'] / rolling_peak - 1.0
    is_crisis = (ivv_vol > crisis_threshold) | (ivv_drawdown < -max_drawdown_limit)

    signal_df = pd.DataFrame(index=aligned_index)
    signal_df['ivv_vol'] = ivv_vol
    signal_df['xau_vol'] = xau_vol
    signal_df['corr'] = corr
    signal_df['is_crisis'] = is_crisis.astype(float)
    signal_df['ivv_target'] = risk_parity_ivv
    signal_df['xau_target'] = risk_parity_xau
    signal_df.loc[signal_df['is_crisis'] > 0.5, 'ivv_target'] = crisis_ivv_weight
    signal_df.loc[signal_df['is_crisis'] > 0.5, 'xau_target'] = crisis_xau_weight
    signal_df.loc[ivv_drawdown < -max_drawdown_limit, 'ivv_target'] *= reduced_total_exposure
    signal_df.loc[ivv_drawdown < -max_drawdown_limit, 'xau_target'] *= reduced_total_exposure
    signal_df['total_target'] = signal_df['ivv_target'] + signal_df['xau_target']
    signal_df = signal_df.dropna().copy()

    prepared_map = {
        'ivv3x': ivv.loc[signal_df.index].copy(),
        'xau3x': xau.loc[signal_df.index].copy(),
    }
    return prepared_map, signal_df, signal_df.index


class DualAssetLeveragedStrategy(bt.Strategy):
    params = dict(
        signal_lookup=None,
        rebalance_interval_days=21,
        rebalance_threshold=0.05,
        ivv_leverage=3.0,
        xauusd_leverage=3.0,
        use_risk_parity=True,
        use_crisis_detection=True,
        crisis_vol_threshold=0.3,
        crisis_equity_weight=0.2,
        crisis_gold_weight=0.8,
        max_drawdown_limit=0.2,
        reduced_total_exposure=0.5,
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
            return {name: 0.0 for name in ASSET_NAMES}
        weights = {}
        for name in ASSET_NAMES:
            data = self.data_by_name[name]
            position = self.getposition(data)
            weights[name] = float(position.size) * float(data.close[0]) / portfolio_value if position.size else 0.0
        return weights

    def _rebalance(self, targets):
        current_weights = self._portfolio_weights()
        for name in ASSET_NAMES:
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
            'ivv3x': float(signal.get('ivv_target', 0.0)),
            'xau3x': float(signal.get('xau_target', 0.0)),
        }
        current_weights = self._portfolio_weights()
        if any(abs(current_weights.get(name, 0.0) - targets.get(name, 0.0)) > float(self.p.rebalance_threshold) for name in ASSET_NAMES):
            self._rebalance(targets)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [pending for pending in self.pending_orders if pending is not None and pending.ref != order.ref]
