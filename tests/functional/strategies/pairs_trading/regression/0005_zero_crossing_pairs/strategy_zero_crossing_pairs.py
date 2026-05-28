from __future__ import absolute_import, division, print_function, unicode_literals

import io

import numpy as np
import pandas as pd
import backtrader as bt

ASSET_ORDER = ['XAUUSD', 'XAGUSD']


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    if 'time' in df.columns:
        df['datetime'] = pd.to_datetime(df['time'], errors='coerce', utc=True).dt.tz_convert(None)
        if 'volume' not in df.columns:
            df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
        df['openinterest'] = 0
        df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
        df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
        if fromdate is not None:
            df = df[df.index >= fromdate]
        if todate is not None:
            df = df[df.index <= todate]
        return df
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
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


def _rolling_beta(y, x, window):
    beta = pd.Series(np.nan, index=y.index)
    for i in range(window, len(y)):
        y_window = y.iloc[i - window:i]
        x_window = x.iloc[i - window:i]
        x_var = np.var(x_window.values)
        if x_var <= 0:
            continue
        beta.iloc[i] = np.cov(y_window.values, x_window.values)[0, 1] / x_var
    return beta


def prepare_zero_crossing_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    close_df = pd.DataFrame({name: frame['close'] for name, frame in aligned.items()}, index=common_index).dropna()
    aligned = {name: frame.loc[close_df.index].copy() for name, frame in aligned.items()}

    hedge_window = int(params.get('hedge_window', 60))
    zscore_window = int(params.get('zscore_window', 20))
    exit_z = float(params.get('exit_z', 0.5))
    gross_exposure = float(params.get('gross_exposure', 1.0))

    gold_close = close_df['XAUUSD']
    silver_close = close_df['XAGUSD']
    hedge_ratio = _rolling_beta(gold_close, silver_close, hedge_window)
    spread = gold_close - hedge_ratio * silver_close
    spread_mean = spread.rolling(zscore_window).mean()
    spread_std = spread.rolling(zscore_window).std()
    zscore = (spread - spread_mean) / spread_std

    position_signal = pd.Series(0.0, index=close_df.index)
    position = 0.0
    for i in range(max(hedge_window, zscore_window), len(close_df)):
        z = zscore.iloc[i]
        prev_z = zscore.iloc[i - 1]
        if pd.isna(z) or pd.isna(prev_z):
            continue
        if position == 0:
            if prev_z < 0 and z > 0:
                position = 1.0
            elif prev_z > 0 and z < 0:
                position = -1.0
        elif position == 1.0:
            if z > exit_z:
                position = 0.0
        elif position == -1.0:
            if z < -exit_z:
                position = 0.0
        position_signal.iloc[i] = position
    position_signal = position_signal.replace(0, np.nan).ffill().fillna(0.0)
    rebalance_flag = position_signal.ne(position_signal.shift(1)).astype(float)

    abs_beta = hedge_ratio.abs().clip(lower=0.01)
    gold_notional = gold_close
    silver_notional = abs_beta * silver_close
    denom = (gold_notional + silver_notional).replace(0, np.nan)
    raw_gold_weight = gross_exposure * gold_notional / denom
    raw_silver_weight = gross_exposure * silver_notional / denom

    gold_weight = position_signal * raw_gold_weight
    silver_weight = -position_signal * raw_silver_weight

    signal_df = aligned['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['hedge_ratio'] = hedge_ratio
    signal_df['zscore'] = zscore
    signal_df['position_signal'] = position_signal
    signal_df['rebalance_flag'] = rebalance_flag
    signal_df['gold_weight'] = gold_weight
    signal_df['silver_weight'] = silver_weight
    signal_df = signal_df[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'hedge_ratio', 'zscore', 'position_signal', 'rebalance_flag', 'gold_weight', 'silver_weight']]
    return {'signal_df': signal_df.dropna(), 'asset_frames': aligned}


class ZeroCrossSignalFeed(bt.feeds.PandasData):
    lines = ('hedge_ratio', 'zscore', 'position_signal', 'rebalance_flag', 'gold_weight', 'silver_weight')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('hedge_ratio', 6), ('zscore', 7), ('position_signal', 8), ('rebalance_flag', 9), ('gold_weight', 10), ('silver_weight', 11),
    )


class ZeroCrossingPairsStrategy(bt.Strategy):
    params = dict(
        hedge_window=60,
        zscore_window=20,
        exit_z=0.5,
        gross_exposure=1.0,
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
