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


def prepare_paired_switching_data(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    asset_frames = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    momentum_window = int(params.get('momentum_window', 63))
    volatility_window = int(params.get('volatility_window', 63))
    min_score_gap = float(params.get('min_score_gap', 0.05))

    returns = pd.DataFrame(index=common_index)
    returns['xau_ret'] = asset_frames['XAUUSD']['close'].pct_change()
    returns['xag_ret'] = asset_frames['XAGUSD']['close'].pct_change()
    xau_momentum = returns['xau_ret'].rolling(momentum_window).mean()
    xag_momentum = returns['xag_ret'].rolling(momentum_window).mean()
    xau_vol = returns['xau_ret'].rolling(volatility_window).std().replace(0, np.nan)
    xag_vol = returns['xag_ret'].rolling(volatility_window).std().replace(0, np.nan)
    xau_score = xau_momentum / xau_vol
    xag_score = xag_momentum / xag_vol
    month_end = pd.Series(common_index, index=common_index).dt.to_period('M') != pd.Series(common_index, index=common_index).shift(-1).dt.to_period('M')

    selected = []
    active_asset = 'CASH'
    for idx in common_index:
        if pd.isna(xau_score.loc[idx]) or pd.isna(xag_score.loc[idx]):
            selected.append(active_asset)
            continue
        if not month_end.loc[idx]:
            selected.append(active_asset)
            continue
        diff = xau_score.loc[idx] - xag_score.loc[idx]
        if xau_score.loc[idx] < 0 and xag_score.loc[idx] < 0:
            active_asset = 'CASH'
        elif diff > min_score_gap and xau_score.loc[idx] > 0:
            active_asset = 'XAUUSD'
        elif diff < -min_score_gap and xag_score.loc[idx] > 0:
            active_asset = 'XAGUSD'
        selected.append(active_asset)

    summary = pd.DataFrame(index=common_index)
    summary['selected_asset'] = selected
    summary['selected_asset_code'] = pd.Series(selected, index=common_index).map({'CASH': 0, 'XAUUSD': 1, 'XAGUSD': 2}).fillna(0).astype(float)
    summary['rebalance_flag'] = month_end.astype(float)
    summary['xau_score'] = xau_score
    summary['xag_score'] = xag_score
    signal_df = asset_frames['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['selected_asset_code'] = summary['selected_asset_code']
    signal_df['rebalance_flag'] = summary['rebalance_flag']
    signal_df['xau_score'] = summary['xau_score']
    signal_df['xag_score'] = summary['xag_score']
    signal_df = signal_df.dropna(subset=['xau_score', 'xag_score'])
    asset_frames = {name: frame.loc[signal_df.index].copy() for name, frame in asset_frames.items()}
    summary = summary.loc[signal_df.index].copy()
    return signal_df, asset_frames, summary


class GoldPairedSwitchingSignalFeed(bt.feeds.PandasData):
    lines = ('selected_asset_code', 'rebalance_flag', 'xau_score', 'xag_score')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('selected_asset_code', 6), ('rebalance_flag', 7), ('xau_score', 8), ('xag_score', 9),
    )


class GoldPairedSwitchingStrategy(bt.Strategy):
    params = dict(
        momentum_window=63,
        volatility_window=63,
        min_score_gap=0.05,
        rebalance_month_end_only=True,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_map = {'XAUUSD': self.getdatabyname('XAUUSD'), 'XAGUSD': self.getdatabyname('XAGUSD')}
        self.code_to_asset = {0: 'CASH', 1: 'XAUUSD', 2: 'XAGUSD'}
        self.bar_num = 0
        self.rebalance_count = 0
        self.switch_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order_refs = set()
        self.last_selected_asset = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order_refs:
            return
        if float(self.signal.rebalance_flag[0]) < 0.5:
            return
        asset_code = int(round(float(self.signal.selected_asset_code[0]))) if self.signal.selected_asset_code[0] == self.signal.selected_asset_code[0] else 0
        selected_asset = self.code_to_asset.get(asset_code, 'CASH')
        if self.last_selected_asset == selected_asset:
            return
        if self.last_selected_asset is not None:
            self.switch_count += 1
        self.last_selected_asset = selected_asset
        self.rebalance_count += 1
        for asset_name, data in self.asset_map.items():
            target = 1.0 if asset_name == selected_asset else 0.0
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
