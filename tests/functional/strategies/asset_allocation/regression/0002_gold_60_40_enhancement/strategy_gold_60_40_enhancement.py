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


def prepare_gold_60_40_enhancement_data(asset_daily_frames, params):
    monthly_frames = {name: resample_to_monthly(frame) for name, frame in asset_daily_frames.items()}
    common_index = None
    for frame in monthly_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    monthly_frames = {name: frame.loc[common_index].copy() for name, frame in monthly_frames.items()}

    gold_base_weight = float(params.get('gold_base_weight', 0.10))
    gold_min_weight = float(params.get('gold_min_weight', 0.05))
    gold_max_weight = float(params.get('gold_max_weight', 0.25))
    equity_vol_lookback = int(params.get('equity_vol_lookback_months', 3))
    bond_signal_lookback = int(params.get('bond_signal_lookback_months', 3))
    gold_trend_lookback = int(params.get('gold_trend_lookback_months', 12))

    close_table = pd.DataFrame({name: frame['close'] for name, frame in monthly_frames.items()}, index=common_index)
    returns = close_table.pct_change()

    equity_vol = returns['IVV'].rolling(equity_vol_lookback).std() * np.sqrt(12)
    equity_vol_ma = equity_vol.rolling(12).mean()
    risk_off_signal = (equity_vol > equity_vol_ma).astype(float).fillna(0.0)

    bond_signal = (close_table['IEF'].pct_change(bond_signal_lookback) > 0).astype(float).fillna(0.0)
    gold_trend_signal = (close_table['XAUUSD'].pct_change(gold_trend_lookback) > 0).astype(float).fillna(0.0)

    gold_weight = gold_base_weight + 0.05 * risk_off_signal + 0.03 * bond_signal + 0.02 * gold_trend_signal
    gold_weight = gold_weight.clip(lower=gold_min_weight, upper=gold_max_weight)
    remaining = 1.0 - gold_weight
    equity_weight = remaining * 0.60
    bond_weight = remaining * 0.40

    periods = pd.Series(common_index, index=common_index).dt.to_period('Q')
    rebalance_flag = (periods != periods.shift(-1)).astype(float)

    signal_df = monthly_frames['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['risk_off_signal'] = risk_off_signal
    signal_df['bond_signal'] = bond_signal
    signal_df['gold_trend_signal'] = gold_trend_signal
    signal_df['gold_weight'] = gold_weight
    signal_df['equity_weight'] = equity_weight
    signal_df['bond_weight'] = bond_weight
    signal_df['rebalance_flag'] = rebalance_flag

    summary = pd.DataFrame({
        'XAUUSD': close_table['XAUUSD'],
        'IVV': close_table['IVV'],
        'IEF': close_table['IEF'],
        'risk_off_signal': risk_off_signal,
        'bond_signal': bond_signal,
        'gold_trend_signal': gold_trend_signal,
        'gold_weight': gold_weight,
        'equity_weight': equity_weight,
        'bond_weight': bond_weight,
    }).dropna()

    signal_df = signal_df.loc[summary.index].copy()
    monthly_frames = {name: frame.loc[summary.index].copy() for name, frame in monthly_frames.items()}
    return signal_df, monthly_frames, summary


class Gold6040SignalFeed(bt.feeds.PandasData):
    lines = ('risk_off_signal', 'bond_signal', 'gold_trend_signal', 'gold_weight', 'equity_weight', 'bond_weight', 'rebalance_flag')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('risk_off_signal', 6), ('bond_signal', 7), ('gold_trend_signal', 8), ('gold_weight', 9), ('equity_weight', 10), ('bond_weight', 11), ('rebalance_flag', 12),
    )


class Gold6040EnhancementStrategy(bt.Strategy):
    params = dict(
        gold_base_weight=0.10,
        gold_min_weight=0.05,
        gold_max_weight=0.25,
        equity_base_weight=0.55,
        bond_base_weight=0.35,
        rebalance_frequency="quarterly",
        equity_vol_lookback_months=3,
        bond_signal_lookback_months=3,
        gold_trend_lookback_months=12,
        rebalance_threshold=0.05,
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
        for name, data in self.asset_feeds.items():
            position_value = float(self.getposition(data).size) * float(data.close[0])
            current_weight = position_value / float(self.broker.getvalue()) if self.broker.getvalue() else 0.0
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
