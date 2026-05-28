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


def _rolling_beta_alpha(y, x, window):
    beta = pd.Series(np.nan, index=y.index)
    alpha = pd.Series(np.nan, index=y.index)
    for i in range(window, len(y)):
        y_window = y.iloc[i - window:i]
        x_window = x.iloc[i - window:i]
        x_mean = x_window.mean()
        y_mean = y_window.mean()
        x_var = ((x_window - x_mean) ** 2).sum()
        if x_var <= 0:
            continue
        cov = ((x_window - x_mean) * (y_window - y_mean)).sum()
        b = cov / x_var
        a = y_mean - b * x_mean
        beta.iloc[i] = b
        alpha.iloc[i] = a
    return beta, alpha


def prepare_cointegrated_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    close_df = pd.DataFrame({name: frame['close'] for name, frame in aligned.items()}, index=common_index).dropna()
    aligned = {name: frame.loc[close_df.index].copy() for name, frame in aligned.items()}

    regression_window = int(params.get('regression_window', 30))
    zscore_window = int(params.get('zscore_window', 40))
    entry_threshold = float(params.get('entry_threshold', 2.5))
    exit_threshold = float(params.get('exit_threshold', 0.5))
    stop_loss = float(params.get('stop_loss', 0.05))
    pair_notional_fraction = float(params.get('pair_notional_fraction', 0.10))

    gold_close = close_df['XAUUSD']
    silver_close = close_df['XAGUSD']
    beta, alpha = _rolling_beta_alpha(gold_close, silver_close, regression_window)
    spread = gold_close - beta * silver_close + alpha
    spread_mean = spread.shift(1).rolling(zscore_window).mean()
    spread_std = spread.shift(1).rolling(zscore_window).std()
    zscore = (spread - spread_mean) / spread_std.replace(0, np.nan)

    gold_weight = pd.Series(0.0, index=close_df.index)
    silver_weight = pd.Series(0.0, index=close_df.index)
    rebalance_flag = pd.Series(0.0, index=close_df.index)
    position_state = pd.Series(0.0, index=close_df.index)

    position = 0
    entry_gold = None
    entry_silver = None
    entry_beta = None

    for i, dt in enumerate(close_df.index):
        b = beta.iloc[i]
        z = zscore.iloc[i]
        if pd.isna(b) or pd.isna(z):
            continue
        abs_beta = max(abs(b), 0.01)
        leg_unit = pair_notional_fraction / (1.0 + abs_beta)
        target_gold = 0.0
        target_silver = 0.0
        signal_changed = False

        if position == 0:
            if z < -entry_threshold:
                position = 1
                entry_gold = gold_close.iloc[i]
                entry_silver = silver_close.iloc[i]
                entry_beta = abs_beta
                signal_changed = True
            elif z > entry_threshold:
                position = -1
                entry_gold = gold_close.iloc[i]
                entry_silver = silver_close.iloc[i]
                entry_beta = abs_beta
                signal_changed = True
        else:
            pnl_y = 0.0
            pnl_x = 0.0
            if position == 1:
                pnl_y = (gold_close.iloc[i] - entry_gold) / entry_gold
                pnl_x = (entry_silver - silver_close.iloc[i]) / entry_silver
            elif position == -1:
                pnl_y = (entry_gold - gold_close.iloc[i]) / entry_gold
                pnl_x = (silver_close.iloc[i] - entry_silver) / entry_silver
            total_pnl = (pnl_y + pnl_x * entry_beta) / (1.0 + entry_beta)
            if abs(z) <= exit_threshold or total_pnl <= -stop_loss:
                position = 0
                signal_changed = True
                entry_gold = None
                entry_silver = None
                entry_beta = None

        if position == 1:
            target_gold = leg_unit
            target_silver = -leg_unit * abs_beta
        elif position == -1:
            target_gold = -leg_unit
            target_silver = leg_unit * abs_beta

        gold_weight.iloc[i] = target_gold
        silver_weight.iloc[i] = target_silver
        rebalance_flag.iloc[i] = 1.0 if signal_changed else 0.0
        position_state.iloc[i] = float(position)

    signal_df = aligned['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['beta'] = beta
    signal_df['zscore'] = zscore
    signal_df['position_state'] = position_state
    signal_df['rebalance_flag'] = rebalance_flag
    signal_df['gold_weight'] = gold_weight
    signal_df['silver_weight'] = silver_weight
    signal_df = signal_df[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'beta', 'zscore', 'position_state', 'rebalance_flag', 'gold_weight', 'silver_weight']]
    return {'signal_df': signal_df.dropna(), 'asset_frames': aligned}


class CointegratedSignalFeed(bt.feeds.PandasData):
    lines = ('beta', 'zscore', 'position_state', 'rebalance_flag', 'gold_weight', 'silver_weight')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('beta', 6), ('zscore', 7), ('position_state', 8), ('rebalance_flag', 9), ('gold_weight', 10), ('silver_weight', 11),
    )


class CointegratedPairsStrategy(bt.Strategy):
    params = dict(
        regression_window=30,
        zscore_window=40,
        entry_threshold=2.5,
        exit_threshold=0.5,
        stop_loss=0.05,
        pair_notional_fraction=0.1,
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
        target_map = {
            'XAUUSD': float(self.signal_data.gold_weight[0]),
            'XAGUSD': float(self.signal_data.silver_weight[0]),
        }
        for symbol, target in target_map.items():
            order = self.order_target_percent(data=self.asset_data[symbol], target=target)
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
