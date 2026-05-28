from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd
from scipy import stats

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


def empirical_cdf(sample, value):
    sorted_sample = np.sort(np.asarray(sample, dtype=float))
    rank = np.searchsorted(sorted_sample, float(value), side='right')
    u = (rank + 1.0) / (len(sorted_sample) + 2.0)
    return float(np.clip(u, 1e-4, 1.0 - 1e-4))


def clayton_theta_from_tau(u, v):
    tau = stats.kendalltau(u, v).correlation
    if tau is None or not np.isfinite(tau) or tau <= 0:
        return 0.10
    theta = 2.0 * tau / max(1e-6, 1.0 - tau)
    return float(max(theta, 0.10))


def clayton_conditional(u, v, theta):
    u = float(np.clip(u, 1e-4, 1.0 - 1e-4))
    v = float(np.clip(v, 1e-4, 1.0 - 1e-4))
    term1 = u ** (-(theta + 1.0))
    term2 = (u ** (-theta) + v ** (-theta) - 1.0) ** (-(theta + 1.0) / theta)
    value = term1 * term2
    return float(np.clip(value, 0.0, 1.0))


def rolling_beta(y, x):
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    x_var = np.sum((x - x_mean) ** 2)
    if x_var <= 0:
        return 1.0
    cov = np.sum((x - x_mean) * (y - y_mean))
    beta = cov / x_var
    return float(beta if np.isfinite(beta) else 1.0)


def prepare_copula_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    close_df = pd.DataFrame({name: frame['close'] for name, frame in aligned.items()}, index=common_index).dropna()
    aligned = {name: frame.loc[close_df.index].copy() for name, frame in aligned.items()}
    returns = close_df.pct_change()

    lookback = int(params.get('lookback', 252))
    entry_threshold = float(params.get('entry_threshold', 0.05))
    exit_band = float(params.get('exit_band', 0.10))
    pair_notional_fraction = float(params.get('pair_notional_fraction', 0.10))

    theta_series = pd.Series(np.nan, index=close_df.index)
    prob_series = pd.Series(np.nan, index=close_df.index)
    beta_series = pd.Series(np.nan, index=close_df.index)
    position_state = pd.Series(0.0, index=close_df.index)
    rebalance_flag = pd.Series(0.0, index=close_df.index)
    gold_weight = pd.Series(0.0, index=close_df.index)
    silver_weight = pd.Series(0.0, index=close_df.index)

    position = 0
    for i in range(lookback + 1, len(close_df)):
        hist_returns = returns.iloc[i - lookback:i].dropna()
        if len(hist_returns) < lookback:
            continue
        gold_hist = hist_returns['XAUUSD'].values
        silver_hist = hist_returns['XAGUSD'].values
        current_gold_ret = float(returns.iloc[i]['XAUUSD'])
        current_silver_ret = float(returns.iloc[i]['XAGUSD'])
        u = empirical_cdf(gold_hist, current_gold_ret)
        v = empirical_cdf(silver_hist, current_silver_ret)
        theta = clayton_theta_from_tau(gold_hist, silver_hist)
        prob_v_given_u = clayton_conditional(u, v, theta)
        beta = abs(rolling_beta(silver_hist, gold_hist))
        beta = max(beta, 0.10)

        theta_series.iloc[i] = theta
        prob_series.iloc[i] = prob_v_given_u
        beta_series.iloc[i] = beta

        signal_changed = False
        if position == 0:
            if prob_v_given_u < entry_threshold:
                position = 1
                signal_changed = True
            elif prob_v_given_u > 1.0 - entry_threshold:
                position = -1
                signal_changed = True
        else:
            if abs(prob_v_given_u - 0.5) <= exit_band:
                position = 0
                signal_changed = True

        leg_unit = pair_notional_fraction / (1.0 + beta)
        target_gold = 0.0
        target_silver = 0.0
        if position == 1:
            target_gold = -leg_unit * beta
            target_silver = leg_unit
        elif position == -1:
            target_gold = leg_unit * beta
            target_silver = -leg_unit

        position_state.iloc[i] = float(position)
        rebalance_flag.iloc[i] = 1.0 if signal_changed else 0.0
        gold_weight.iloc[i] = target_gold
        silver_weight.iloc[i] = target_silver

    signal_df = aligned['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['theta'] = theta_series
    signal_df['copula_prob'] = prob_series
    signal_df['beta'] = beta_series
    signal_df['position_state'] = position_state
    signal_df['rebalance_flag'] = rebalance_flag
    signal_df['gold_weight'] = gold_weight
    signal_df['silver_weight'] = silver_weight
    signal_df = signal_df[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'theta', 'copula_prob', 'beta', 'position_state', 'rebalance_flag', 'gold_weight', 'silver_weight']]
    return {'signal_df': signal_df.dropna(), 'asset_frames': aligned}


class CopulaSignalFeed(bt.feeds.PandasData):
    lines = ('theta', 'copula_prob', 'beta', 'position_state', 'rebalance_flag', 'gold_weight', 'silver_weight')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('theta', 6), ('copula_prob', 7), ('beta', 8), ('position_state', 9), ('rebalance_flag', 10), ('gold_weight', 11), ('silver_weight', 12),
    )


class CopulaPairsStrategy(bt.Strategy):
    params = dict(
        lookback=252,
        entry_threshold=0.05,
        exit_band=0.1,
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
