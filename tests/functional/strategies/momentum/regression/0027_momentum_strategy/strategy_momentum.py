from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSET_NAMES = ('IVV', 'GLD', 'DBC', 'IEF')


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


def prepare_momentum_data(asset_daily_frames, params):
    monthly_frames = {name: resample_to_monthly(frame) for name, frame in asset_daily_frames.items()}
    common_index = None
    for frame in monthly_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    monthly_frames = {name: frame.loc[common_index].copy() for name, frame in monthly_frames.items()}
    close_table = pd.DataFrame({name: frame['close'] for name, frame in monthly_frames.items()}, index=common_index)
    returns_1m = close_table.pct_change()
    lookback = int(params.get('lookback_months', 12))
    vol_lookback = int(params.get('vol_lookback_months', 6))
    n_long = int(params.get('n_long', 2))
    n_short = int(params.get('n_short', 2))
    target_vol = float(params.get('volatility_target', 0.15))
    max_weight = float(params.get('max_weight_per_asset', 0.40))
    momentum = close_table.pct_change(lookback)
    realized_vol = returns_1m.rolling(vol_lookback).std() * np.sqrt(12.0)

    signal_df = monthly_frames['GLD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    for asset in ASSET_NAMES:
        signal_df[f'{asset.lower()}_momentum'] = momentum[asset]
        signal_df[f'{asset.lower()}_vol'] = realized_vol[asset]
        signal_df[f'{asset.lower()}_weight'] = 0.0
    signal_df['gross_exposure'] = 0.0
    signal_df['long_count'] = 0.0
    signal_df['short_count'] = 0.0

    for idx in signal_df.index:
        row_mom = momentum.loc[idx].dropna()
        row_vol = realized_vol.loc[idx].dropna()
        if len(row_mom) < len(ASSET_NAMES) or len(row_vol) < len(ASSET_NAMES):
            continue
        ranked = row_mom.sort_values(ascending=False)
        long_assets = [asset for asset in ranked.index[:n_long] if row_mom[asset] > 0]
        short_assets = [asset for asset in ranked.index[-n_short:] if row_mom[asset] < 0]
        for asset in long_assets:
            vol = max(float(row_vol[asset]), 1e-6)
            weight = min(max_weight, (target_vol / vol) / max(1, len(long_assets) + len(short_assets)))
            signal_df.at[idx, f'{asset.lower()}_weight'] = weight
        for asset in short_assets:
            vol = max(float(row_vol[asset]), 1e-6)
            weight = min(max_weight, (target_vol / vol) / max(1, len(long_assets) + len(short_assets)))
            signal_df.at[idx, f'{asset.lower()}_weight'] = -weight
        gross = sum(abs(float(signal_df.at[idx, f'{asset.lower()}_weight'])) for asset in ASSET_NAMES)
        signal_df.at[idx, 'gross_exposure'] = gross
        signal_df.at[idx, 'long_count'] = float(len(long_assets))
        signal_df.at[idx, 'short_count'] = float(len(short_assets))

    signal_df = signal_df.dropna().copy()
    monthly_summary = pd.DataFrame(index=signal_df.index)
    for asset in ASSET_NAMES:
        monthly_summary[asset] = close_table.loc[signal_df.index, asset]
        monthly_summary[f'{asset.lower()}_momentum'] = momentum.loc[signal_df.index, asset]
        monthly_summary[f'{asset.lower()}_weight'] = signal_df[f'{asset.lower()}_weight']
    monthly_summary['gross_exposure'] = signal_df['gross_exposure']
    monthly_summary['long_count'] = signal_df['long_count']
    monthly_summary['short_count'] = signal_df['short_count']
    monthly_frames = {name: frame.loc[signal_df.index].copy() for name, frame in monthly_frames.items()}
    return signal_df, monthly_frames, monthly_summary


class MomentumSignalFeed(bt.feeds.PandasData):
    lines = (
        'ivv_momentum', 'gld_momentum', 'dbc_momentum', 'ief_momentum',
        'ivv_vol', 'gld_vol', 'dbc_vol', 'ief_vol',
        'ivv_weight', 'gld_weight', 'dbc_weight', 'ief_weight',
        'gross_exposure', 'long_count', 'short_count',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('ivv_momentum', 6), ('gld_momentum', 7), ('dbc_momentum', 8), ('ief_momentum', 9),
        ('ivv_vol', 10), ('gld_vol', 11), ('dbc_vol', 12), ('ief_vol', 13),
        ('ivv_weight', 14), ('gld_weight', 15), ('dbc_weight', 16), ('ief_weight', 17),
        ('gross_exposure', 18), ('long_count', 19), ('short_count', 20),
    )


class MomentumStrategy(bt.Strategy):
    params = dict(
        rebalance_tolerance=0.02,
        lookback_months=12,
        holding_period_months=1,
        n_long=2,
        n_short=2,
        vol_lookback_months=6,
        volatility_target=0.15,
        max_weight_per_asset=0.4,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_feeds = {name: self.getdatabyname(name) for name in ASSET_NAMES}
        self.bar_num = 0
        self.rebalance_count = 0
        self.switch_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.short_count = 0
        self.cover_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order_refs = set()
        self.last_weight_map = None
        self.broker_value_series = []
        self.long_months = 0
        self.short_months = 0
        self.cash_months = 0

    def _target_map(self):
        return {
            'IVV': float(self.signal.ivv_weight[0]),
            'GLD': float(self.signal.gld_weight[0]),
            'DBC': float(self.signal.dbc_weight[0]),
            'IEF': float(self.signal.ief_weight[0]),
        }

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        target_map = self._target_map()
        long_count = sum(1 for weight in target_map.values() if weight > 0)
        short_count = sum(1 for weight in target_map.values() if weight < 0)
        if long_count > 0:
            self.long_months += 1
        if short_count > 0:
            self.short_months += 1
        if long_count == 0 and short_count == 0:
            self.cash_months += 1
        if self.pending_order_refs:
            return
        if self.last_weight_map == target_map:
            return
        if self.last_weight_map is not None:
            self.switch_count += 1
        self.last_weight_map = dict(target_map)
        self.rebalance_count += 1
        for name, data in self.asset_feeds.items():
            target_pct = float(target_map[name])
            current_position = self.getposition(data).size
            order = self.order_target_percent(data=data, target=target_pct)
            if order is not None:
                self.pending_order_refs.add(order.ref)
                if target_pct > 0 and current_position <= 0:
                    self.buy_count += 1
                elif target_pct < 0 and current_position >= 0:
                    self.short_count += 1
                elif target_pct == 0 and current_position > 0:
                    self.sell_count += 1
                elif target_pct == 0 and current_position < 0:
                    self.cover_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
