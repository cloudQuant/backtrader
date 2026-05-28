from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSETS = ('XAUUSD', 'IVV', 'IEF', 'DBC')
ASSET_CODE_MAP = {'CASH': 0, 'XAUUSD': 1, 'IVV': 2, 'IEF': 3, 'DBC': 4}


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


def resample_to_monthly(df):
    monthly = pd.DataFrame({
        'open': df['open'].resample('ME').first(),
        'high': df['high'].resample('ME').max(),
        'low': df['low'].resample('ME').min(),
        'close': df['close'].resample('ME').last(),
        'volume': df['volume'].resample('ME').sum(),
        'openinterest': df['openinterest'].resample('ME').last().fillna(0),
    })
    return monthly.dropna(subset=['open', 'high', 'low', 'close'])


def prepare_asset_rotation_data(asset_daily_frames, params):
    monthly_frames = {name: resample_to_monthly(frame) for name, frame in asset_daily_frames.items()}
    common_index = None
    for frame in monthly_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    monthly_frames = {name: frame.loc[common_index].copy() for name, frame in monthly_frames.items()}

    lookback_months = int(params.get('lookback_months', 3))
    top1_weight = float(params.get('top1_weight', 0.7))
    top2_weight = float(params.get('top2_weight', 0.3))
    threshold = float(params.get('absolute_momentum_threshold', 0.0))
    defensive_asset = str(params.get('defensive_asset', 'IEF'))

    closes = pd.DataFrame({name: frame['close'] for name, frame in monthly_frames.items()}, index=common_index)
    momentum = closes / closes.shift(lookback_months) - 1.0

    records = []
    for idx in common_index:
        scores = momentum.loc[idx].dropna().sort_values(ascending=False)
        weights = {asset: 0.0 for asset in ASSETS}
        top1 = 'CASH'
        top2 = 'CASH'
        top1_score = np.nan
        top2_score = np.nan
        if not scores.empty:
            top1 = str(scores.index[0])
            top1_score = float(scores.iloc[0])
            if len(scores) > 1:
                top2 = str(scores.index[1])
                top2_score = float(scores.iloc[1])
            if top1_score > threshold:
                if pd.notna(top2_score) and top2_score > threshold:
                    weights[top1] = top1_weight
                    weights[top2] = top2_weight
                else:
                    weights[top1] = 1.0
            else:
                weights[defensive_asset] = 1.0
                top1 = defensive_asset
                top2 = 'CASH'
                top1_score = scores.get(defensive_asset, np.nan)
                top2_score = np.nan
        else:
            weights[defensive_asset] = 1.0
            top1 = defensive_asset
            top2 = 'CASH'

        records.append({
            'datetime': idx,
            'top1_asset': top1,
            'top2_asset': top2,
            'top1_code': float(ASSET_CODE_MAP.get(top1, 0)),
            'top2_code': float(ASSET_CODE_MAP.get(top2, 0)),
            'top1_score': top1_score,
            'top2_score': top2_score,
            'weight_xau': weights['XAUUSD'],
            'weight_ivv': weights['IVV'],
            'weight_ief': weights['IEF'],
            'weight_dbc': weights['DBC'],
            'xau_momentum': momentum.loc[idx, 'XAUUSD'] if 'XAUUSD' in momentum.columns else np.nan,
            'ivv_momentum': momentum.loc[idx, 'IVV'] if 'IVV' in momentum.columns else np.nan,
            'ief_momentum': momentum.loc[idx, 'IEF'] if 'IEF' in momentum.columns else np.nan,
            'dbc_momentum': momentum.loc[idx, 'DBC'] if 'DBC' in momentum.columns else np.nan,
        })

    summary = pd.DataFrame(records).set_index('datetime')
    signal_df = monthly_frames['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['top1_code'] = summary['top1_code']
    signal_df['top2_code'] = summary['top2_code']
    signal_df['top1_score'] = summary['top1_score']
    signal_df['top2_score'] = summary['top2_score']
    signal_df['weight_xau'] = summary['weight_xau']
    signal_df['weight_ivv'] = summary['weight_ivv']
    signal_df['weight_ief'] = summary['weight_ief']
    signal_df['weight_dbc'] = summary['weight_dbc']
    signal_df['xau_momentum'] = summary['xau_momentum']
    signal_df['ivv_momentum'] = summary['ivv_momentum']
    signal_df['ief_momentum'] = summary['ief_momentum']
    signal_df['dbc_momentum'] = summary['dbc_momentum']
    signal_df = signal_df.dropna(subset=['xau_momentum', 'ivv_momentum', 'ief_momentum', 'dbc_momentum'])
    summary = summary.loc[signal_df.index].copy()
    monthly_frames = {name: frame.loc[signal_df.index].copy() for name, frame in monthly_frames.items()}
    return signal_df, monthly_frames, summary


class GoldAssetRotationSignalFeed(bt.feeds.PandasData):
    lines = ('top1_code', 'top2_code', 'top1_score', 'top2_score', 'weight_xau', 'weight_ivv', 'weight_ief', 'weight_dbc', 'xau_momentum', 'ivv_momentum', 'ief_momentum', 'dbc_momentum')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('top1_code', 6), ('top2_code', 7), ('top1_score', 8), ('top2_score', 9), ('weight_xau', 10), ('weight_ivv', 11), ('weight_ief', 12), ('weight_dbc', 13), ('xau_momentum', 14), ('ivv_momentum', 15), ('ief_momentum', 16), ('dbc_momentum', 17),
    )


class GoldAssetRotationStrategy(bt.Strategy):
    params = dict(
        lookback_months=3,
        top1_weight=0.7,
        top2_weight=0.3,
        absolute_momentum_threshold=0.0,
        defensive_asset='IEF',
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_map = {name: self.getdatabyname(name) for name in ASSETS}
        self.bar_num = 0
        self.rebalance_count = 0
        self.switch_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order_refs = set()
        self.last_weights = None
        self.broker_value_series = []

    def _target_map(self):
        return {
            'XAUUSD': float(self.signal.weight_xau[0]),
            'IVV': float(self.signal.weight_ivv[0]),
            'IEF': float(self.signal.weight_ief[0]),
            'DBC': float(self.signal.weight_dbc[0]),
        }

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order_refs:
            return
        targets = self._target_map()
        if self.last_weights == targets:
            return
        if self.last_weights is not None:
            self.switch_count += 1
        self.last_weights = dict(targets)
        self.rebalance_count += 1
        for asset_name, data in self.asset_map.items():
            target = targets[asset_name]
            current_position = self.getposition(data).size
            order = self.order_target_percent(data=data, target=target)
            if order is not None:
                self.pending_order_refs.add(order.ref)
                if target > 0 and current_position <= 0:
                    self.buy_count += 1
                elif target == 0 and current_position > 0:
                    self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order_refs.discard(order.ref)
