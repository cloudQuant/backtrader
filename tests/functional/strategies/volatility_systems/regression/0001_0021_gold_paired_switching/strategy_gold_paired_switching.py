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


def compute_atr(df, window):
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def prepare_paired_switching_data(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    asset_frames = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    ret_short = int(params.get('ret_short_lookback', 20))
    ret_long = int(params.get('ret_long_lookback', 60))
    atr_lookback = int(params.get('atr_lookback', 20))
    min_switch_threshold = float(params.get('min_switch_threshold', 0.5))
    confirmation_periods = int(params.get('confirmation_periods', 2))
    rebalance_weekday = int(params.get('rebalance_weekday', 4))

    xau = asset_frames['XAUUSD']
    xag = asset_frames['XAGUSD']
    xau_ret_score = 0.5 * (xau['close'] / xau['close'].shift(ret_short) - 1.0) + 0.5 * (xau['close'] / xau['close'].shift(ret_long) - 1.0)
    xag_ret_score = 0.5 * (xag['close'] / xag['close'].shift(ret_short) - 1.0) + 0.5 * (xag['close'] / xag['close'].shift(ret_long) - 1.0)
    xau_risk = compute_atr(xau, atr_lookback) / xau['close']
    xag_risk = compute_atr(xag, atr_lookback) / xag['close']
    xau_adj = xau_ret_score / xau_risk.replace(0, np.nan)
    xag_adj = xag_ret_score / xag_risk.replace(0, np.nan)
    rebalance_flag = (pd.Series(common_index, index=common_index).dt.weekday == rebalance_weekday).astype(float)

    selected_assets = []
    active_asset = 'CASH'
    pending_asset = None
    pending_count = 0

    for idx in common_index:
        if rebalance_flag.loc[idx] < 0.5 or pd.isna(xau_adj.loc[idx]) or pd.isna(xag_adj.loc[idx]):
            selected_assets.append(active_asset)
            continue
        diff = xau_adj.loc[idx] - xag_adj.loc[idx]
        candidate = 'CASH'
        if xau_ret_score.loc[idx] > 0 and diff > min_switch_threshold:
            candidate = 'XAUUSD'
        elif xag_ret_score.loc[idx] > 0 and diff < -min_switch_threshold:
            candidate = 'XAGUSD'
        if candidate == active_asset:
            pending_asset = None
            pending_count = 0
        else:
            if candidate == pending_asset:
                pending_count += 1
            else:
                pending_asset = candidate
                pending_count = 1
            if pending_count >= confirmation_periods:
                active_asset = candidate
                pending_asset = None
                pending_count = 0
        selected_assets.append(active_asset)

    summary = pd.DataFrame(index=common_index)
    summary['selected_asset'] = selected_assets
    summary['selected_asset_code'] = pd.Series(selected_assets, index=common_index).map({'CASH': 0, 'XAUUSD': 1, 'XAGUSD': 2}).fillna(0).astype(float)
    summary['rebalance_flag'] = rebalance_flag
    summary['xau_ret_score'] = xau_ret_score
    summary['xag_ret_score'] = xag_ret_score
    summary['xau_risk'] = xau_risk
    summary['xag_risk'] = xag_risk
    summary['xau_adj_score'] = xau_adj
    summary['xag_adj_score'] = xag_adj
    signal_df = xau[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['selected_asset_code'] = summary['selected_asset_code']
    signal_df['rebalance_flag'] = summary['rebalance_flag']
    signal_df['xau_ret_score'] = summary['xau_ret_score']
    signal_df['xag_ret_score'] = summary['xag_ret_score']
    signal_df['xau_risk'] = summary['xau_risk']
    signal_df['xag_risk'] = summary['xag_risk']
    signal_df['xau_adj_score'] = summary['xau_adj_score']
    signal_df['xag_adj_score'] = summary['xag_adj_score']
    signal_df = signal_df.dropna(subset=['xau_ret_score', 'xag_ret_score', 'xau_adj_score', 'xag_adj_score'])
    asset_frames = {name: frame.loc[signal_df.index].copy() for name, frame in asset_frames.items()}
    summary = summary.loc[signal_df.index].copy()
    return signal_df, asset_frames, summary


class GoldPairedSwitchingSignalFeed(bt.feeds.PandasData):
    lines = ('selected_asset_code', 'rebalance_flag', 'xau_ret_score', 'xag_ret_score', 'xau_risk', 'xag_risk', 'xau_adj_score', 'xag_adj_score')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('selected_asset_code', 6), ('rebalance_flag', 7), ('xau_ret_score', 8), ('xag_ret_score', 9), ('xau_risk', 10), ('xag_risk', 11), ('xau_adj_score', 12), ('xag_adj_score', 13),
    )


class GoldPairedSwitchingStrategy(bt.Strategy):
    params = dict(
        ret_short_lookback=20,
        ret_long_lookback=60,
        atr_lookback=20,
        min_switch_threshold=0.5,
        confirmation_periods=2,
        rebalance_weekday=4,
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
        self.cash_days = 0
        self.xau_days = 0
        self.xag_days = 0

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order_refs:
            return
        asset_code = int(round(float(self.signal.selected_asset_code[0]))) if self.signal.selected_asset_code[0] == self.signal.selected_asset_code[0] else 0
        selected_asset = self.code_to_asset.get(asset_code, 'CASH')
        if selected_asset == 'CASH':
            self.cash_days += 1
        elif selected_asset == 'XAUUSD':
            self.xau_days += 1
        elif selected_asset == 'XAGUSD':
            self.xag_days += 1
        if float(self.signal.rebalance_flag[0]) < 0.5:
            return
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
