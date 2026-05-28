from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSET_NAMES = ('XAUUSD', 'IVV', 'IEF')


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


def rolling_clip_signal(series, lookback):
    vol = series.rolling(lookback).std().replace(0, np.nan)
    signal = (series / vol).clip(lower=-1.0, upper=1.0)
    return signal.fillna(0.0)


def prepare_tactical_allocation_data(asset_daily_frames, params):
    monthly_frames = {name: resample_to_monthly(frame) for name, frame in asset_daily_frames.items()}
    common_index = None
    for frame in monthly_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    monthly_frames = {name: frame.loc[common_index].copy() for name, frame in monthly_frames.items()}

    gold_base_weight = float(params.get('gold_base_weight', 0.10))
    gold_min_weight = float(params.get('gold_min_weight', 0.05))
    gold_max_weight = float(params.get('gold_max_weight', 0.25))
    tactical_deviation = float(params.get('tactical_deviation', 0.10))
    momentum_lookback = int(params.get('momentum_lookback_months', 12))
    equity_vol_lookback = int(params.get('equity_vol_lookback_months', 3))
    rates_lookback = int(params.get('rates_lookback_months', 3))

    close_table = pd.DataFrame({name: frame['close'] for name, frame in monthly_frames.items()}, index=common_index)
    monthly_returns = close_table.pct_change()

    gold_momentum_raw = close_table['XAUUSD'].pct_change(momentum_lookback)
    gold_momentum_signal = rolling_clip_signal(gold_momentum_raw, momentum_lookback)

    equity_vol = monthly_returns['IVV'].rolling(equity_vol_lookback).std() * np.sqrt(12)
    equity_vol_change = equity_vol.pct_change(3).replace([np.inf, -np.inf], np.nan)
    safe_haven_signal = pd.Series(np.where(equity_vol_change > 0.2, 1.0, np.where(equity_vol_change < -0.2, -0.5, 0.0)), index=common_index).fillna(0.0)

    rate_proxy_raw = close_table['IEF'].pct_change(rates_lookback)
    inflation_signal = rolling_clip_signal(rate_proxy_raw, max(6, momentum_lookback // 2))

    combined_signal = 0.4 * gold_momentum_signal + 0.3 * safe_haven_signal + 0.3 * inflation_signal
    combined_signal = combined_signal.clip(lower=-1.0, upper=1.0)

    gold_weight = (gold_base_weight + tactical_deviation * combined_signal).clip(lower=gold_min_weight, upper=gold_max_weight)
    remaining_weight = 1.0 - gold_weight
    ivv_weight = remaining_weight * (0.60 / 0.90)
    ief_weight = remaining_weight * (0.30 / 0.90)

    signal_df = monthly_frames['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['gold_momentum_signal'] = gold_momentum_signal
    signal_df['safe_haven_signal'] = safe_haven_signal
    signal_df['inflation_signal'] = inflation_signal
    signal_df['combined_signal'] = combined_signal
    signal_df['gold_weight'] = gold_weight
    signal_df['ivv_weight'] = ivv_weight
    signal_df['ief_weight'] = ief_weight
    signal_df['rebalance_flag'] = 1.0

    monthly_summary = pd.DataFrame({
        'XAUUSD': close_table['XAUUSD'],
        'IVV': close_table['IVV'],
        'IEF': close_table['IEF'],
        'gold_momentum_signal': gold_momentum_signal,
        'safe_haven_signal': safe_haven_signal,
        'inflation_signal': inflation_signal,
        'combined_signal': combined_signal,
        'gold_weight': gold_weight,
        'ivv_weight': ivv_weight,
        'ief_weight': ief_weight,
    }).dropna()
    signal_df = signal_df.loc[monthly_summary.index].copy()
    monthly_frames = {name: frame.loc[monthly_summary.index].copy() for name, frame in monthly_frames.items()}
    return signal_df, monthly_frames, monthly_summary


class TacticalAllocationSignalFeed(bt.feeds.PandasData):
    lines = ('gold_momentum_signal', 'safe_haven_signal', 'inflation_signal', 'combined_signal', 'gold_weight', 'ivv_weight', 'ief_weight', 'rebalance_flag')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('gold_momentum_signal', 6), ('safe_haven_signal', 7), ('inflation_signal', 8), ('combined_signal', 9), ('gold_weight', 10), ('ivv_weight', 11), ('ief_weight', 12), ('rebalance_flag', 13),
    )


class GoldTacticalAllocationStrategy(bt.Strategy):
    params = dict(
        gold_base_weight=0.10,
        gold_min_weight=0.05,
        gold_max_weight=0.25,
        tactical_deviation=0.10,
        momentum_lookback_months=12,
        equity_vol_lookback_months=3,
        rates_lookback_months=3,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_feeds = {
            'XAUUSD': self.getdatabyname('XAUUSD'),
            'IVV': self.getdatabyname('IVV'),
            'IEF': self.getdatabyname('IEF'),
        }
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.rebalance_count = 0
        self.pending_order_refs = set()
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order_refs:
            return
        if float(self.signal.rebalance_flag[0]) <= 0.5:
            return
        self.rebalance_count += 1
        target_map = {
            'XAUUSD': float(self.signal.gold_weight[0]),
            'IVV': float(self.signal.ivv_weight[0]),
            'IEF': float(self.signal.ief_weight[0]),
        }
        for name, data in self.asset_feeds.items():
            target_pct = max(0.0, min(1.0, target_map[name]))
            current_size = self.getposition(data).size
            order = self.order_target_percent(data=data, target=target_pct)
            if order is not None:
                self.pending_order_refs.add(order.ref)
                if target_pct > 0 and current_size <= 0:
                    self.buy_count += 1
                elif target_pct == 0 and current_size > 0:
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
