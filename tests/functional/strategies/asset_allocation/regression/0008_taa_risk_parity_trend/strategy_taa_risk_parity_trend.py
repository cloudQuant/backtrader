from __future__ import absolute_import, division, print_function, unicode_literals

import io

import numpy as np
import backtrader as bt
import pandas as pd


ASSET_ORDER = ['GLD', 'IVV', 'IEF', 'DBC']


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


def _compute_final_weights(monthly_prices, params):
    ma_months = int(params.get('ma_months', 10))
    vol_months = int(params.get('vol_months', 12))
    cash_floor = float(params.get('cash_floor', 0.10))
    max_asset_weight = float(params.get('max_asset_weight', 0.40))
    monthly_returns = monthly_prices.pct_change().dropna()
    if len(monthly_prices) < max(ma_months, vol_months) + 1:
        return pd.Series(0.0, index=monthly_prices.columns)
    vol = monthly_returns.tail(vol_months).std() * np.sqrt(12)
    vol = vol.replace(0, np.nan)
    vol = vol.fillna(vol[vol > 0].mean() if (vol > 0).any() else 0.1)
    risk_inverse = 1.0 / vol
    rp_weights = risk_inverse / risk_inverse.sum()
    ma = monthly_prices.rolling(ma_months).mean().iloc[-1]
    current = monthly_prices.iloc[-1]
    trend_mask = current > ma
    active_weights = pd.Series(0.0, index=monthly_prices.columns)
    for asset in monthly_prices.columns:
        if bool(trend_mask.get(asset, False)):
            active_weights[asset] = float(rp_weights[asset])
    total_active = float(active_weights.sum())
    if total_active > 0:
        active_weights = active_weights / total_active
    investable = max(0.0, 1.0 - cash_floor)
    active_weights = active_weights * investable
    active_weights = active_weights.clip(upper=max_asset_weight)
    total_after_clip = float(active_weights.sum())
    if total_after_clip > investable and total_after_clip > 0:
        active_weights = active_weights / total_after_clip * investable
    return active_weights


def prepare_taa_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    close_df = pd.DataFrame({name: frame['close'] for name, frame in aligned.items()}, index=common_index).dropna()
    aligned = {name: frame.loc[close_df.index].copy() for name, frame in aligned.items()}
    monthly_prices = close_df.resample('ME').last().dropna()
    rebalance_dates = pd.DatetimeIndex(monthly_prices.index)
    signal_df = aligned['GLD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df = signal_df.loc[signal_df.index.isin(rebalance_dates)].copy()
    weight_records = []
    for dt in signal_df.index:
        hist_monthly = monthly_prices.loc[:dt]
        weights = _compute_final_weights(hist_monthly, params)
        weight_records.append(weights)
    weight_df = pd.DataFrame(weight_records, index=signal_df.index).fillna(0.0)
    for asset in ASSET_ORDER:
        signal_df[f'weight_{asset.lower()}'] = weight_df[asset].astype(float)
    signal_df['cash_weight'] = (1.0 - weight_df.sum(axis=1)).clip(lower=0.0)
    aligned = {name: frame.loc[signal_df.index].copy() for name, frame in aligned.items()}
    return aligned, signal_df


class TAASignalFeed(bt.feeds.PandasData):
    lines = ('weight_gld', 'weight_ivv', 'weight_ief', 'weight_dbc', 'cash_weight')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('weight_gld', 6), ('weight_ivv', 7), ('weight_ief', 8), ('weight_dbc', 9), ('cash_weight', 10),
    )


class TAARiskParityTrendStrategy(bt.Strategy):
    params = dict(
        lot_size=1.0,
        ma_months=10,
        vol_months=12,
        rebalance_freq='M',
        cash_floor=0.1,
        max_asset_weight=0.4,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_map = {name: self.getdatabyname(name) for name in ASSET_ORDER}
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.rebalance_count = 0
        self.switch_count = 0
        self.last_weights = None
        self.broker_value_series = []

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
        return round(broker_value * float(self.p.lot_size) * float(target_pct) / (price * multiplier), 2)

    def _target_map(self):
        return {
            'GLD': float(self.signal.weight_gld[0]),
            'IVV': float(self.signal.weight_ivv[0]),
            'IEF': float(self.signal.weight_ief[0]),
            'DBC': float(self.signal.weight_dbc[0]),
        }

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        targets = self._target_map()
        if self.last_weights is not None and all(abs(targets[k] - self.last_weights.get(k, 0.0)) < 1e-9 for k in targets):
            return
        if self.last_weights is not None:
            self.switch_count += 1
        self.last_weights = dict(targets)
        self.rebalance_count += 1
        for asset_name, data in self.asset_map.items():
            current_size = float(self.getposition(data).size)
            order = self.order_target_size(data=data, target=self._target_size(data, targets[asset_name]))
            self._submit(order)
            if order is not None:
                if targets[asset_name] > 0 and current_size <= 0:
                    self.buy_count += 1
                elif targets[asset_name] <= 0 and current_size > 0:
                    self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)
