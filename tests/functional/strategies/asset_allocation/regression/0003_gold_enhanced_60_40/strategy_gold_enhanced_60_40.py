from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

TRADE_ASSETS = ('XAUUSD', 'IVV', 'IEF')
SIGNAL_ASSETS = ('XAUUSD', 'IVV', 'IEF', 'GTIP')


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


def prepare_enhanced_60_40_data(asset_daily_frames, params):
    monthly_frames = {name: resample_to_monthly(frame) for name, frame in asset_daily_frames.items()}
    common_index = None
    for frame in monthly_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    monthly_frames = {name: frame.loc[common_index].copy() for name, frame in monthly_frames.items()}

    close_table = pd.DataFrame({name: frame['close'] for name, frame in monthly_frames.items()}, index=common_index)
    returns = close_table.pct_change()

    macro_lookback = int(params.get('macro_lookback_months', 3))
    gold_trend_lookback = int(params.get('gold_trend_lookback_months', 6))
    equity_vol_lookback = int(params.get('equity_vol_lookback_months', 3))
    gold_min_weight = float(params.get('gold_min_weight', 0.10))
    gold_base_weight = float(params.get('gold_base_weight', 0.20))
    gold_high_weight = float(params.get('gold_high_weight', 0.30))
    gold_max_weight = float(params.get('gold_max_weight', 0.35))

    inflation_up = (close_table['GTIP'].pct_change(macro_lookback) > close_table['IEF'].pct_change(macro_lookback)).astype(float)
    bond_tailwind = (close_table['IEF'].pct_change(macro_lookback) > 0).astype(float)
    risk_off = (
        (close_table['IVV'].pct_change(macro_lookback) < 0) |
        ((returns['IVV'].rolling(equity_vol_lookback).std() * np.sqrt(12)) > (returns['IVV'].rolling(12).std() * np.sqrt(12)))
    ).astype(float)
    gold_trend = (close_table['XAUUSD'].pct_change(gold_trend_lookback) > 0).astype(float)

    macro_score = inflation_up + bond_tailwind + risk_off + gold_trend
    gold_weight = pd.Series(gold_base_weight, index=common_index, dtype=float)
    gold_weight = gold_weight.where(macro_score < 1, gold_base_weight)
    gold_weight = gold_weight.where(macro_score < 3, gold_high_weight)
    gold_weight = gold_weight.where(macro_score < 4, gold_max_weight)
    gold_weight = gold_weight.where(macro_score > 0, gold_min_weight)
    gold_weight = gold_weight.clip(lower=gold_min_weight, upper=gold_max_weight)

    remaining = 1.0 - gold_weight
    equity_share = pd.Series(0.625, index=common_index)
    equity_share = equity_share.where(risk_off < 0.5, 0.45)
    bond_share = 1.0 - equity_share
    equity_weight = remaining * equity_share
    bond_weight = remaining * bond_share

    rebalance_flag = pd.Series(1.0, index=common_index)
    rebalance_flag.iloc[0] = 1.0

    signal_df = monthly_frames['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['inflation_up'] = inflation_up
    signal_df['dollar_weak'] = bond_tailwind
    signal_df['risk_off'] = risk_off
    signal_df['gold_trend'] = gold_trend
    signal_df['macro_score'] = macro_score
    signal_df['gold_weight'] = gold_weight
    signal_df['equity_weight'] = equity_weight
    signal_df['bond_weight'] = bond_weight
    signal_df['rebalance_flag'] = rebalance_flag

    summary = pd.DataFrame({
        'XAUUSD': close_table['XAUUSD'],
        'IVV': close_table['IVV'],
        'IEF': close_table['IEF'],
        'GTIP': close_table['GTIP'],
        'macro_score': macro_score,
        'gold_weight': gold_weight,
        'equity_weight': equity_weight,
        'bond_weight': bond_weight,
    }).dropna()

    signal_df = signal_df.loc[summary.index].copy()
    monthly_frames = {name: frame.loc[summary.index].copy() for name, frame in monthly_frames.items()}
    return signal_df, monthly_frames, summary


class GoldEnhanced6040SignalFeed(bt.feeds.PandasData):
    lines = ('inflation_up', 'dollar_weak', 'risk_off', 'gold_trend', 'macro_score', 'gold_weight', 'equity_weight', 'bond_weight', 'rebalance_flag')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('inflation_up', 6), ('dollar_weak', 7), ('risk_off', 8), ('gold_trend', 9), ('macro_score', 10), ('gold_weight', 11), ('equity_weight', 12), ('bond_weight', 13), ('rebalance_flag', 14),
    )


class GoldEnhanced6040Strategy(bt.Strategy):
    params = dict(
        gold_min_weight=0.10,
        gold_base_weight=0.20,
        gold_high_weight=0.30,
        gold_max_weight=0.35,
        rebalance_frequency="monthly",
        rebalance_threshold=0.05,
        macro_lookback_months=3,
        gold_trend_lookback_months=6,
        equity_vol_lookback_months=3,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_feeds = {name: self.getdatabyname(name) for name in TRADE_ASSETS}
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order_refs = set()
        self.broker_value_series = []

    def _target_map(self):
        return {
            'XAUUSD': float(self.signal.gold_weight[0]),
            'IVV': float(self.signal.equity_weight[0]),
            'IEF': float(self.signal.bond_weight[0]),
        }

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order_refs:
            return
        if float(self.signal.rebalance_flag[0]) <= 0.5:
            return
        targets = self._target_map()
        need_rebalance = False
        broker_value = float(self.broker.getvalue())
        for name, data in self.asset_feeds.items():
            position_value = float(self.getposition(data).size) * float(data.close[0])
            current_weight = position_value / broker_value if broker_value else 0.0
            if abs(targets[name] - current_weight) >= float(self.p.rebalance_threshold):
                need_rebalance = True
                break
        if not need_rebalance and self.bar_num > 1:
            return
        for name, data in self.asset_feeds.items():
            target_pct = max(0.0, min(1.0, targets[name]))
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
