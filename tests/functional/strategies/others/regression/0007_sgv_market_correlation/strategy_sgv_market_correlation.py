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


def _calculate_sgv(window_returns):
    cov_matrix = window_returns.cov().values.astype(float)
    cov_matrix = cov_matrix + np.eye(cov_matrix.shape[0]) * 1e-12
    det = float(np.linalg.det(cov_matrix))
    if not np.isfinite(det):
        return np.nan
    det = max(abs(det), 0.0)
    n_assets = cov_matrix.shape[0]
    return det ** (1.0 / n_assets) if n_assets > 0 else np.nan


def prepare_sgv_inputs(monitor_frames, trade_frames, params):
    common_index = None
    for frame in list(monitor_frames.values()) + list(trade_frames.values()):
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()

    monitor_frames = {name: frame.loc[common_index].copy() for name, frame in monitor_frames.items()}
    trade_frames = {name: frame.loc[common_index].copy() for name, frame in trade_frames.items()}

    sgv_window = int(params.get('sgv_window', 252))
    sgv_high_lookback = int(params.get('sgv_high_lookback', 126))
    zscore_window = int(params.get('zscore_window', 126))
    regime_threshold = float(params.get('regime_threshold', 1.75))

    monitor_close = pd.DataFrame({name: frame['close'] for name, frame in monitor_frames.items()}, index=common_index)
    log_returns = np.log(monitor_close / monitor_close.shift(1))

    sgv_values = pd.Series(np.nan, index=common_index, dtype='float64')
    for idx in range(sgv_window, len(log_returns)):
        window_returns = log_returns.iloc[idx - sgv_window + 1:idx + 1].dropna()
        if len(window_returns) < sgv_window:
            continue
        sgv_values.iloc[idx] = _calculate_sgv(window_returns)

    prior_high = sgv_values.shift(1).rolling(sgv_high_lookback).max()
    rolling_mean = sgv_values.rolling(zscore_window).mean()
    rolling_std = sgv_values.rolling(zscore_window).std().replace(0.0, np.nan)
    zscore = (sgv_values - rolling_mean) / rolling_std
    crisis_flag = ((sgv_values >= prior_high) | (zscore >= regime_threshold)).astype(float)

    selected_asset = []
    active_asset = 'IEF'
    for idx in common_index:
        sgv = sgv_values.loc[idx]
        high = prior_high.loc[idx]
        z_val = zscore.loc[idx]
        if pd.isna(sgv) or pd.isna(high) or pd.isna(z_val):
            selected_asset.append(active_asset)
            continue
        if sgv >= high or z_val >= regime_threshold:
            active_asset = 'IEF'
        else:
            active_asset = 'GLD'
        selected_asset.append(active_asset)

    summary = pd.DataFrame(index=common_index)
    summary['selected_asset'] = selected_asset
    summary['selected_asset_code'] = pd.Series(selected_asset, index=common_index).map({'IEF': 1, 'GLD': 2}).astype(float)
    summary['sgv'] = sgv_values
    summary['prior_sgv_high'] = prior_high
    summary['sgv_zscore'] = zscore
    summary['crisis_flag'] = crisis_flag
    summary['rebalance_flag'] = summary['selected_asset'].ne(summary['selected_asset'].shift(1)).astype(float)
    summary['gold_signal'] = (summary['selected_asset'] == 'GLD').astype(float)
    summary['bond_signal'] = (summary['selected_asset'] == 'IEF').astype(float)

    signal_df = trade_frames['GLD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['selected_asset_code'] = summary['selected_asset_code']
    signal_df['sgv'] = summary['sgv']
    signal_df['prior_sgv_high'] = summary['prior_sgv_high']
    signal_df['sgv_zscore'] = summary['sgv_zscore']
    signal_df['crisis_flag'] = summary['crisis_flag']
    signal_df['gold_signal'] = summary['gold_signal']
    signal_df['bond_signal'] = summary['bond_signal']
    signal_df['rebalance_flag'] = summary['rebalance_flag']
    signal_df['signal_change'] = signal_df['selected_asset_code'].ne(signal_df['selected_asset_code'].shift(1)).astype(float)
    signal_df = signal_df.dropna(subset=['sgv', 'prior_sgv_high', 'sgv_zscore'])

    trade_frames = {name: frame.loc[signal_df.index].copy() for name, frame in trade_frames.items()}
    summary = summary.loc[signal_df.index].copy()
    return signal_df, trade_frames, summary


class SGVSignalFeed(bt.feeds.PandasData):
    lines = ('selected_asset_code', 'sgv', 'prior_sgv_high', 'sgv_zscore', 'crisis_flag', 'gold_signal', 'bond_signal', 'rebalance_flag', 'signal_change')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('selected_asset_code', 6), ('sgv', 7), ('prior_sgv_high', 8), ('sgv_zscore', 9), ('crisis_flag', 10),
        ('gold_signal', 11), ('bond_signal', 12), ('rebalance_flag', 13), ('signal_change', 14),
    )


class SGVMarketCorrelationStrategy(bt.Strategy):
    params = dict(
        invest_pct=0.99,
        sgv_window=252,
        sgv_high_lookback=126,
        zscore_window=126,
        regime_threshold=1.75,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_map = {'IEF': self.getdatabyname('IEF'), 'GLD': self.getdatabyname('GLD')}
        self.code_to_asset = {1: 'IEF', 2: 'GLD'}
        self.bar_num = 0
        self.rebalance_count = 0
        self.switch_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order_refs = set()
        self.last_selected_asset = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order_refs:
            return
        if float(self.signal.signal_change[0]) <= 0.5:
            return
        asset_code = int(round(float(self.signal.selected_asset_code[0]))) if self.signal.selected_asset_code[0] == self.signal.selected_asset_code[0] else 1
        selected_asset = self.code_to_asset.get(asset_code, 'IEF')
        if self.last_selected_asset == selected_asset:
            return
        if self.last_selected_asset is not None:
            self.switch_count += 1
        self.last_selected_asset = selected_asset
        self.rebalance_count += 1
        for asset_name, data in self.asset_map.items():
            target = float(self.p.invest_pct) if asset_name == selected_asset else 0.0
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

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
