from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSET_ORDER = ['XAUUSD', 'XAGUSD']


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


def prepare_vol_corr_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    close_df = pd.DataFrame({name: frame['close'] for name, frame in aligned.items()}, index=common_index).dropna()
    aligned = {name: frame.loc[close_df.index].copy() for name, frame in aligned.items()}

    corr_window = int(params.get('corr_window', 20))
    mean_window = int(params.get('mean_window', 126))
    threshold_sigma = float(params.get('threshold_sigma', 1.5))
    vol_window = int(params.get('vol_window', 20))
    exit_z = float(params.get('exit_z', 0.5))
    gross_exposure = float(params.get('gross_exposure', 0.8))

    returns = close_df.pct_change()
    correlation = returns['XAUUSD'].rolling(corr_window).corr(returns['XAGUSD'])
    corr_mean = correlation.rolling(mean_window).mean()
    corr_std = correlation.rolling(mean_window).std().replace(0.0, np.nan)
    corr_zscore = (correlation - corr_mean) / corr_std

    gold_vol = returns['XAUUSD'].rolling(vol_window).std() * np.sqrt(252.0)
    silver_vol = returns['XAGUSD'].rolling(vol_window).std() * np.sqrt(252.0)

    signal = pd.Series(0.0, index=close_df.index)
    position = 0.0
    start_idx = max(corr_window, mean_window, vol_window)
    for i in range(start_idx, len(close_df)):
        z = corr_zscore.iloc[i]
        if pd.isna(z):
            signal.iloc[i] = position
            continue
        if position == 0.0:
            if z > threshold_sigma:
                position = 1.0
            elif z < -threshold_sigma:
                position = -1.0
        elif position == 1.0:
            if z < exit_z:
                position = 0.0
        elif position == -1.0:
            if z > -exit_z:
                position = 0.0
        signal.iloc[i] = position
    signal = signal.replace(0, np.nan).ffill().fillna(0.0)
    rebalance_flag = signal.ne(signal.shift(1)).astype(float)

    inv_gold_vol = (1.0 / gold_vol.replace(0.0, np.nan)).clip(upper=1e6)
    inv_silver_vol = (1.0 / silver_vol.replace(0.0, np.nan)).clip(upper=1e6)
    vol_sum = (inv_gold_vol + inv_silver_vol).replace(0.0, np.nan)
    gold_base_weight = gross_exposure * inv_gold_vol / vol_sum
    silver_base_weight = gross_exposure * inv_silver_vol / vol_sum

    gold_weight = signal * gold_base_weight
    silver_weight = -signal * silver_base_weight

    signal_df = aligned['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['correlation'] = correlation
    signal_df['corr_mean'] = corr_mean
    signal_df['corr_std'] = corr_std
    signal_df['corr_zscore'] = corr_zscore
    signal_df['gold_vol'] = gold_vol
    signal_df['silver_vol'] = silver_vol
    signal_df['position_signal'] = signal
    signal_df['rebalance_flag'] = rebalance_flag
    signal_df['gold_weight'] = gold_weight
    signal_df['silver_weight'] = silver_weight
    signal_df = signal_df[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'correlation', 'corr_mean', 'corr_std', 'corr_zscore', 'gold_vol', 'silver_vol', 'position_signal', 'rebalance_flag', 'gold_weight', 'silver_weight']]
    return {'signal_df': signal_df.dropna(), 'asset_frames': aligned}


class VolCorrSignalFeed(bt.feeds.PandasData):
    lines = ('correlation', 'corr_mean', 'corr_std', 'corr_zscore', 'gold_vol', 'silver_vol', 'position_signal', 'rebalance_flag', 'gold_weight', 'silver_weight')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('correlation', 6), ('corr_mean', 7), ('corr_std', 8), ('corr_zscore', 9), ('gold_vol', 10), ('silver_vol', 11),
        ('position_signal', 12), ('rebalance_flag', 13), ('gold_weight', 14), ('silver_weight', 15),
    )


class VolatilityCorrelationModelStrategy(bt.Strategy):
    params = dict(
        corr_window=20,
        mean_window=126,
        threshold_sigma=1.5,
        vol_window=20,
        exit_z=0.5,
        gross_exposure=0.8,
    )

    def __init__(self):
        self.signal_data = self.datas[0]
        self.asset_data = {data._name: data for data in self.datas[1:]}
        self.pending_orders = []
        self.bar_num = 0
        self.rebalance_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal_data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_orders:
            return
        if float(self.signal_data.rebalance_flag[0]) <= 0.5:
            return
        self.rebalance_count += 1
        order1 = self.order_target_percent(data=self.asset_data['XAUUSD'], target=float(self.signal_data.gold_weight[0]))
        order2 = self.order_target_percent(data=self.asset_data['XAGUSD'], target=float(self.signal_data.silver_weight[0]))
        for order in (order1, order2):
            if order is not None:
                self.pending_orders.append(order)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [o for o in self.pending_orders if o.ref != order.ref]

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
