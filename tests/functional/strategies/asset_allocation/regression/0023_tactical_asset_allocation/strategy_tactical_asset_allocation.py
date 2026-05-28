from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSET_NAMES = ('IVV', 'GLD', 'IEF')


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


def build_regime_frame(ivv_daily, params):
    out = ivv_daily.copy()
    ma_fast = int(params.get('ma_fast', 50))
    ma_slow = int(params.get('ma_slow', 200))
    vol_window = int(params.get('volatility_window', 21))
    vol_threshold = float(params.get('volatility_threshold', 0.20))
    out['returns'] = out['close'].pct_change()
    out['ma_fast'] = out['close'].rolling(ma_fast).mean()
    out['ma_slow'] = out['close'].rolling(ma_slow).mean()
    out['realized_vol'] = out['returns'].rolling(vol_window).std() * np.sqrt(252.0)
    out['trend_up'] = (out['ma_fast'] > out['ma_slow']).astype(float)
    out['vol_high'] = (out['realized_vol'] > vol_threshold).astype(float)
    out['regime'] = 'neutral'
    out.loc[(out['trend_up'] > 0.5) & (out['vol_high'] < 0.5), 'regime'] = 'offensive'
    out.loc[(out['trend_up'] < 0.5) & (out['vol_high'] > 0.5), 'regime'] = 'defensive'
    out['regime_code'] = 1.0
    out.loc[out['regime'] == 'offensive', 'regime_code'] = 2.0
    out.loc[out['regime'] == 'defensive', 'regime_code'] = 0.0
    return out.dropna(subset=['ma_fast', 'ma_slow', 'realized_vol'])


def get_allocation_map(params):
    return {
        'offensive': {
            'IVV': float(params.get('offensive_equity', 0.65)),
            'GLD': float(params.get('offensive_gold', 0.15)),
            'IEF': float(params.get('offensive_bond', 0.15)),
            'cash': float(params.get('offensive_cash', 0.05)),
        },
        'defensive': {
            'IVV': float(params.get('defensive_equity', 0.30)),
            'GLD': float(params.get('defensive_gold', 0.25)),
            'IEF': float(params.get('defensive_bond', 0.35)),
            'cash': float(params.get('defensive_cash', 0.10)),
        },
        'neutral': {
            'IVV': float(params.get('neutral_equity', 0.45)),
            'GLD': float(params.get('neutral_gold', 0.20)),
            'IEF': float(params.get('neutral_bond', 0.30)),
            'cash': float(params.get('neutral_cash', 0.05)),
        },
    }


def prepare_taa_data(asset_daily_frames, params):
    regime_daily = build_regime_frame(asset_daily_frames['IVV'], params)
    monthly_regime = regime_daily.resample('ME').last().dropna(subset=['regime'])
    monthly_frames = {name: resample_to_monthly(frame) for name, frame in asset_daily_frames.items()}
    common_index = monthly_regime.index
    for frame in monthly_frames.values():
        common_index = common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    monthly_regime = monthly_regime.loc[common_index].copy()
    monthly_frames = {name: frame.loc[common_index].copy() for name, frame in monthly_frames.items()}
    allocation_map = get_allocation_map(params)
    signal_df = monthly_frames['IVV'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['regime_code'] = monthly_regime['regime_code']
    signal_df['realized_vol'] = monthly_regime['realized_vol']
    signal_df['ivv_weight'] = 0.0
    signal_df['gld_weight'] = 0.0
    signal_df['ief_weight'] = 0.0
    signal_df['cash_weight'] = 0.0
    signal_df['rebalance_flag'] = 1.0
    for index in signal_df.index:
        regime_name = monthly_regime.at[index, 'regime']
        weights = allocation_map[regime_name]
        signal_df.at[index, 'ivv_weight'] = weights['IVV']
        signal_df.at[index, 'gld_weight'] = weights['GLD']
        signal_df.at[index, 'ief_weight'] = weights['IEF']
        signal_df.at[index, 'cash_weight'] = weights['cash']
    signal_df = signal_df[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'regime_code', 'realized_vol', 'ivv_weight', 'gld_weight', 'ief_weight', 'cash_weight', 'rebalance_flag',
    ]].copy()
    summary_df = pd.DataFrame({
        'IVV': monthly_frames['IVV']['close'],
        'GLD': monthly_frames['GLD']['close'],
        'IEF': monthly_frames['IEF']['close'],
        'regime_code': signal_df['regime_code'],
        'realized_vol': signal_df['realized_vol'],
        'ivv_weight': signal_df['ivv_weight'],
        'gld_weight': signal_df['gld_weight'],
        'ief_weight': signal_df['ief_weight'],
        'cash_weight': signal_df['cash_weight'],
    }).dropna()
    signal_df = signal_df.loc[summary_df.index].copy()
    monthly_frames = {name: frame.loc[summary_df.index].copy() for name, frame in monthly_frames.items()}
    return signal_df, monthly_frames, summary_df


class TacticalAssetAllocationSignalFeed(bt.feeds.PandasData):
    lines = ('regime_code', 'realized_vol', 'ivv_weight', 'gld_weight', 'ief_weight', 'cash_weight', 'rebalance_flag')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('regime_code', 6), ('realized_vol', 7), ('ivv_weight', 8), ('gld_weight', 9), ('ief_weight', 10), ('cash_weight', 11), ('rebalance_flag', 12),
    )


class TacticalAssetAllocationStrategy(bt.Strategy):
    params = dict(
        rebalance_tolerance=0.02,
        ma_fast=50,
        ma_slow=200,
        volatility_window=21,
        volatility_threshold=0.2,
        offensive_equity=0.65,
        offensive_gold=0.15,
        offensive_bond=0.15,
        offensive_cash=0.05,
        defensive_equity=0.3,
        defensive_gold=0.25,
        defensive_bond=0.35,
        defensive_cash=0.1,
        neutral_equity=0.45,
        neutral_gold=0.2,
        neutral_bond=0.3,
        neutral_cash=0.05,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_feeds = {'IVV': self.getdatabyname('IVV'), 'GLD': self.getdatabyname('GLD'), 'IEF': self.getdatabyname('IEF')}
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.rebalance_count = 0
        self.pending_order_refs = set()
        self.broker_value_series = []
        self.offensive_months = 0
        self.defensive_months = 0
        self.neutral_months = 0

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        regime_code = float(self.signal.regime_code[0])
        if regime_code > 1.5:
            self.offensive_months += 1
        elif regime_code < 0.5:
            self.defensive_months += 1
        else:
            self.neutral_months += 1
        if self.pending_order_refs:
            return
        if float(self.signal.rebalance_flag[0]) <= 0.5:
            return
        self.rebalance_count += 1
        target_map = {
            'IVV': float(self.signal.ivv_weight[0]),
            'GLD': float(self.signal.gld_weight[0]),
            'IEF': float(self.signal.ief_weight[0]),
        }
        for name, data in self.asset_feeds.items():
            target_pct = max(0.0, min(1.0, target_map[name]))
            current_value = abs(self.getposition(data).size) * float(data.close[0])
            broker_value = max(float(self.broker.getvalue()), 1e-9)
            current_pct = current_value / broker_value
            if abs(current_pct - target_pct) < float(self.p.rebalance_tolerance):
                continue
            current_size = self.getposition(data).size
            order = self.order_target_percent(data=data, target=target_pct)
            if order is not None:
                self.pending_order_refs.add(order.ref)
                if target_pct > current_pct and current_size >= 0:
                    self.buy_count += 1
                elif target_pct < current_pct and current_size > 0:
                    self.sell_count += 1

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
