from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSET_ORDER = ['GLD', 'GDX', 'XAGUSD', 'IEF']
FACTOR_ORDER = ['IVV']


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


def _rolling_alpha(asset_returns, factor_returns, lookback_window):
    alpha = pd.Series(np.nan, index=asset_returns.index)
    aligned = pd.concat([asset_returns, factor_returns], axis=1).dropna()
    if aligned.empty:
        return alpha
    asset = aligned.iloc[:, 0]
    factor = aligned.iloc[:, 1]
    for i in range(lookback_window, len(aligned) + 1):
        y = asset.iloc[i - lookback_window:i]
        x = factor.iloc[i - lookback_window:i]
        variance = float(np.var(x, ddof=1)) if len(x) > 1 else 0.0
        if variance <= 0:
            intercept = 0.0
        else:
            covariance = float(np.cov(x, y, ddof=1)[0, 1])
            beta = covariance / variance
            intercept = float(y.mean() - beta * x.mean())
        alpha.loc[aligned.index[i - 1]] = intercept * 252.0
    return alpha


def prepare_alpha_momentum_inputs(asset_frames, factor_frames, params):
    common_index = None
    for frame in list(asset_frames.values()) + list(factor_frames.values()):
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    asset_frames = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    factor_frames = {name: frame.loc[common_index].copy() for name, frame in factor_frames.items()}

    lookback_window = int(params.get('lookback_window', 252))
    rebalance_days = int(params.get('rebalance_days', 21))
    signal_delay_days = int(params.get('signal_delay_days', 1))
    gross_exposure = float(params.get('gross_exposure', 0.8))
    selection_count = int(params.get('selection_count', 1))

    asset_close = pd.DataFrame({name: frame['close'] for name, frame in asset_frames.items()}, index=common_index).dropna()
    factor_close = pd.DataFrame({name: frame['close'] for name, frame in factor_frames.items()}, index=common_index).dropna()
    full_index = asset_close.index.intersection(factor_close.index).sort_values()
    asset_close = asset_close.loc[full_index]
    factor_close = factor_close.loc[full_index]
    asset_frames = {name: frame.loc[full_index].copy() for name, frame in asset_frames.items()}

    asset_returns = asset_close.pct_change()
    factor_returns = factor_close['IVV'].pct_change()

    alpha_df = pd.DataFrame(index=full_index)
    for asset in ASSET_ORDER:
        daily_alpha = _rolling_alpha(asset_returns[asset], factor_returns, lookback_window)
        alpha_df[asset] = daily_alpha.rolling(rebalance_days).sum()

    signal_df = asset_frames[ASSET_ORDER[0]][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    for asset in ASSET_ORDER:
        signal_df[f'{asset.lower()}_alpha_mom'] = alpha_df[asset]
        signal_df[f'{asset.lower()}_target'] = 0.0

    rebalance_flag = pd.Series(0.0, index=signal_df.index)
    for i in range(lookback_window, len(signal_df), rebalance_days):
        signal_loc = i + signal_delay_days
        if signal_loc >= len(signal_df.index):
            break
        current_date = signal_df.index[i]
        target_date = signal_df.index[signal_loc]
        scores = alpha_df.loc[current_date].dropna().sort_values()
        if len(scores) < 2:
            continue
        n_select = max(1, min(selection_count, len(scores) // 2))
        short_assets = list(scores.index[:n_select])
        long_assets = list(scores.index[-n_select:])
        long_weight = gross_exposure / 2.0 / len(long_assets)
        short_weight = -gross_exposure / 2.0 / len(short_assets)
        for asset in ASSET_ORDER:
            signal_df.at[target_date, f'{asset.lower()}_target'] = 0.0
        for asset in long_assets:
            signal_df.at[target_date, f'{asset.lower()}_target'] = long_weight
        for asset in short_assets:
            signal_df.at[target_date, f'{asset.lower()}_target'] = short_weight
        rebalance_flag.at[target_date] = 1.0

    target_cols = [f'{asset.lower()}_target' for asset in ASSET_ORDER]
    signal_df[target_cols] = signal_df[target_cols].where(rebalance_flag > 0.5).ffill().fillna(0.0)
    signal_df['rebalance_flag'] = rebalance_flag
    signal_df['signal_change'] = signal_df[target_cols].round(8).ne(signal_df[target_cols].shift(1).round(8)).any(axis=1).astype(float)

    ordered_cols = ['open', 'high', 'low', 'close', 'volume', 'openinterest']
    ordered_cols += [f'{asset.lower()}_alpha_mom' for asset in ASSET_ORDER]
    ordered_cols += target_cols + ['rebalance_flag', 'signal_change']
    signal_df = signal_df[ordered_cols].dropna()
    return {'signal_df': signal_df, 'asset_frames': asset_frames}


class AlphaMomentumFeed(bt.feeds.PandasData):
    lines = (
        'gld_alpha_mom', 'gdx_alpha_mom', 'xagusd_alpha_mom', 'ief_alpha_mom',
        'gld_target', 'gdx_target', 'xagusd_target', 'ief_target',
        'rebalance_flag', 'signal_change',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('gld_alpha_mom', 6), ('gdx_alpha_mom', 7), ('xagusd_alpha_mom', 8), ('ief_alpha_mom', 9),
        ('gld_target', 10), ('gdx_target', 11), ('xagusd_target', 12), ('ief_target', 13),
        ('rebalance_flag', 14), ('signal_change', 15),
    )


class AlphaMomentumStrategyBT(bt.Strategy):
    params = dict(
        lookback_window=252,
        rebalance_days=21,
        signal_delay_days=1,
        gross_exposure=0.8,
        selection_count=1,
        commission_pct=0.0005,
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
        if float(self.signal_data.signal_change[0]) <= 0.5:
            return
        self.rebalance_count += 1
        target_map = {
            'GLD': float(self.signal_data.gld_target[0]),
            'GDX': float(self.signal_data.gdx_target[0]),
            'XAGUSD': float(self.signal_data.xagusd_target[0]),
            'IEF': float(self.signal_data.ief_target[0]),
        }
        for asset, target in target_map.items():
            order = self.order_target_percent(data=self.asset_data[asset], target=target)
            if order is not None:
                self.pending_orders.append(order)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [pending for pending in self.pending_orders if pending.ref != order.ref]

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
