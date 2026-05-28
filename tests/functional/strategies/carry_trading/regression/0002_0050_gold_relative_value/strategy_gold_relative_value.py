from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd

ASSETS = ('XAUUSD', 'XAGUSD', 'XPTUSD')
PAIR_DEFS = (
    ('xag', 'XAUUSD', 'XAGUSD'),
    ('xpt', 'XAUUSD', 'XPTUSD'),
)


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


def rolling_beta(y, x, window):
    cov = y.rolling(window).cov(x)
    var = x.rolling(window).var()
    beta = cov / var.replace(0, np.nan)
    return beta.replace([np.inf, -np.inf], np.nan)


def build_pair_state(zscores, hedge_ratios, entry_z, exit_z, stop_z):
    states = []
    state = 0
    for z, hedge in zip(zscores, hedge_ratios):
        if np.isnan(z) or np.isnan(hedge):
            states.append(0)
            state = 0
            continue
        if state == 0:
            if z > entry_z:
                state = -1
            elif z < -entry_z:
                state = 1
        else:
            if abs(z) < exit_z or abs(z) > stop_z:
                state = 0
        states.append(state)
    return pd.Series(states, index=zscores.index, dtype=float)


def prepare_relative_value_features(gold_df, silver_df, platinum_df, params):
    common_index = gold_df.index.intersection(silver_df.index).intersection(platinum_df.index).sort_values()
    gold = gold_df.loc[common_index].copy()
    silver = silver_df.loc[common_index].copy()
    platinum = platinum_df.loc[common_index].copy()
    frames = {'XAUUSD': gold, 'XAGUSD': silver, 'XPTUSD': platinum}

    lookback_window = int(params.get('lookback_window', 60))
    entry_z = float(params.get('entry_z', 2.0))
    exit_z = float(params.get('exit_z', 0.5))
    stop_z = float(params.get('stop_z', 4.0))
    pair_position_pct = float(params.get('pair_position_pct', 0.25))
    max_total_pct = float(params.get('max_total_pct', 0.60))

    price_table = pd.DataFrame({name: frame['close'] for name, frame in frames.items()}, index=common_index)
    log_prices = np.log(price_table)
    signal_df = gold[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    agg_weights = pd.DataFrame(0.0, index=common_index, columns=list(ASSETS))

    for prefix, left, right in PAIR_DEFS:
        beta = rolling_beta(log_prices[left], log_prices[right], lookback_window)
        spread = log_prices[left] - beta * log_prices[right]
        spread_mean = spread.rolling(lookback_window).mean()
        spread_std = spread.rolling(lookback_window).std()
        zscore = (spread - spread_mean) / spread_std.replace(0, np.nan)
        state = build_pair_state(zscore, beta, entry_z, exit_z, stop_z)
        clipped_beta = beta.clip(lower=0.25, upper=4.0)

        signal_df[f'{prefix}_hedge_ratio'] = clipped_beta
        signal_df[f'{prefix}_spread'] = spread
        signal_df[f'{prefix}_zscore'] = zscore
        signal_df[f'{prefix}_state'] = state

        pair_gold_weight = pair_position_pct * state
        pair_other_weight = -pair_position_pct * clipped_beta * state
        agg_weights[left] = agg_weights[left] + pair_gold_weight.fillna(0.0)
        agg_weights[right] = agg_weights[right] + pair_other_weight.fillna(0.0)

    agg_weights = agg_weights.clip(lower=-max_total_pct, upper=max_total_pct)
    signal_df['weight_xau'] = agg_weights['XAUUSD']
    signal_df['weight_xag'] = agg_weights['XAGUSD']
    signal_df['weight_xpt'] = agg_weights['XPTUSD']
    signal_df = signal_df.dropna(subset=['xag_zscore', 'xpt_zscore'])
    frames = {name: frame.loc[signal_df.index].copy() for name, frame in frames.items()}
    return signal_df, frames


class GoldRelativeValueSignalFeed(bt.feeds.PandasData):
    lines = ('xag_hedge_ratio', 'xag_spread', 'xag_zscore', 'xag_state', 'xpt_hedge_ratio', 'xpt_spread', 'xpt_zscore', 'xpt_state', 'weight_xau', 'weight_xag', 'weight_xpt')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('xag_hedge_ratio', 6), ('xag_spread', 7), ('xag_zscore', 8), ('xag_state', 9), ('xpt_hedge_ratio', 10), ('xpt_spread', 11), ('xpt_zscore', 12), ('xpt_state', 13), ('weight_xau', 14), ('weight_xag', 15), ('weight_xpt', 16),
    )


class GoldRelativeValueStrategy(bt.Strategy):
    params = dict(
        lookback_window=60,
        entry_z=2.0,
        exit_z=0.5,
        stop_z=4.0,
        pair_position_pct=0.25,
        max_total_pct=0.6,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_feeds = {name: self.getdatabyname(name) for name in ASSETS}
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order_refs = set()
        self.broker_value_series = []
        self.last_targets = None

    def _target_map(self):
        return {
            'XAUUSD': float(self.signal.weight_xau[0]),
            'XAGUSD': float(self.signal.weight_xag[0]),
            'XPTUSD': float(self.signal.weight_xpt[0]),
        }

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order_refs:
            return
        targets = self._target_map()
        if self.last_targets == targets:
            return
        self.last_targets = dict(targets)
        for asset_name, data in self.asset_feeds.items():
            target = targets[asset_name]
            current_size = self.getposition(data).size
            order = self.order_target_percent(data=data, target=target)
            if order is not None:
                self.pending_order_refs.add(order.ref)
                if target > 0 and current_size <= 0:
                    self.buy_count += 1
                elif target < 0 and current_size >= 0:
                    self.sell_count += 1
                elif target == 0 and current_size != 0:
                    self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order_refs.discard(order.ref)
