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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


def prepare_pair_data(asset_a_df, asset_b_df):
    common_index = asset_a_df.index.intersection(asset_b_df.index).sort_values()
    asset_a = asset_a_df.loc[common_index].copy()
    asset_b = asset_b_df.loc[common_index].copy()
    return asset_a, asset_b


def prepare_correlation_features(asset_a_df, asset_b_df, params):
    asset_a, asset_b = prepare_pair_data(asset_a_df, asset_b_df)
    window = int(params.get('corr_window', 60))
    threshold_high = float(params.get('corr_threshold_high', 0.7))
    threshold_low = float(params.get('corr_threshold_low', 0.3))
    hold_hedge_scale = float(params.get('hold_hedge_scale', 1.0))
    neutral_hedge_scale = float(params.get('neutral_hedge_scale', 0.75))
    break_hedge_scale = float(params.get('break_hedge_scale', 0.5))

    returns_a = asset_a['close'].pct_change()
    returns_b = asset_b['close'].pct_change()
    rolling_corr = returns_a.rolling(window).corr(returns_b)
    previous_corr = rolling_corr.shift(1)
    corr_change = rolling_corr - previous_corr
    corr_stability = rolling_corr.rolling(window).std()
    rolling_cov = returns_a.rolling(window).cov(returns_b)
    rolling_var = returns_b.rolling(window).var()
    hedge_ratio = (rolling_cov / rolling_var.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    log_a = np.log(asset_a['close'].clip(lower=1e-6))
    log_b = np.log(asset_b['close'].clip(lower=1e-6))
    spread = log_a - hedge_ratio * log_b
    spread_mean = spread.rolling(window).mean()
    spread_std = spread.rolling(window).std()
    zscore = (spread - spread_mean) / spread_std.replace(0, np.nan)

    regime = np.where(rolling_corr >= threshold_high, 2.0, np.where(rolling_corr <= threshold_low, 0.0, 1.0))
    hedge_scale = np.where(regime >= 2.0, hold_hedge_scale, np.where(regime <= 0.0, break_hedge_scale, neutral_hedge_scale))

    signal_df = asset_a[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['rolling_corr'] = rolling_corr.astype(float)
    signal_df['previous_corr'] = previous_corr.astype(float)
    signal_df['corr_change'] = corr_change.astype(float)
    signal_df['corr_stability'] = corr_stability.astype(float)
    signal_df['hedge_ratio'] = hedge_ratio.astype(float)
    signal_df['zscore'] = zscore.astype(float)
    signal_df['regime'] = pd.Series(regime, index=signal_df.index, dtype='float64')
    signal_df['hedge_scale'] = pd.Series(hedge_scale, index=signal_df.index, dtype='float64')
    signal_df['corr_hold'] = (signal_df['regime'] >= 2.0).astype(float)
    signal_df['corr_break'] = (signal_df['regime'] <= 0.0).astype(float)
    signal_df = signal_df.dropna(subset=['rolling_corr', 'previous_corr', 'corr_change', 'corr_stability', 'hedge_ratio', 'zscore'])
    asset_a = asset_a.loc[signal_df.index].copy()
    asset_b = asset_b.loc[signal_df.index].copy()
    return signal_df, asset_a, asset_b


class CorrelationSignalFeed(bt.feeds.PandasData):
    lines = ('rolling_corr', 'previous_corr', 'corr_change', 'corr_stability', 'hedge_ratio', 'zscore', 'regime', 'hedge_scale', 'corr_hold', 'corr_break')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('rolling_corr', 6), ('previous_corr', 7), ('corr_change', 8), ('corr_stability', 9), ('hedge_ratio', 10), ('zscore', 11), ('regime', 12), ('hedge_scale', 13), ('corr_hold', 14), ('corr_break', 15),
    )


class CorrelationBreakHoldStrategy(bt.Strategy):
    params = dict(
        entry_zscore=1.5,
        exit_zscore=0.35,
        stop_zscore=3.0,
        base_notional_pct=0.2,
        min_hedge_ratio=0.1,
        corr_window=60,
        corr_threshold_high=0.7,
        corr_threshold_low=0.3,
        hold_hedge_scale=1.0,
        neutral_hedge_scale=0.75,
        break_hedge_scale=0.5,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_a = self.getdatabyname('XAUUSD')
        self.asset_b = self.getdatabyname('XAGUSD')
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.current_spread_side = 0
        self.broker_value_series = []
        self.hold_regime_days = 0
        self.neutral_regime_days = 0
        self.break_regime_days = 0

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _position_open(self):
        return bool(self.getposition(self.asset_a).size or self.getposition(self.asset_b).size)

    def _target_sizes(self, side, beta, hedge_scale):
        portfolio_value = float(self.broker.getvalue())
        price_a = max(float(self.asset_a.close[0]), 1e-6)
        price_b = max(float(self.asset_b.close[0]), 1e-6)
        base_notional = portfolio_value * float(self.p.base_notional_pct)
        effective_beta = max(abs(float(beta)), float(self.p.min_hedge_ratio))
        scale = max(0.0, float(hedge_scale))
        size_a = max(0.01, round(base_notional / price_a, 2))
        size_b = max(0.01, round(base_notional * effective_beta * scale / price_b, 2))
        if side > 0:
            return size_a, -size_b
        return -size_a, size_b

    def _rebalance_pair(self, side, beta, hedge_scale):
        target_a, target_b = self._target_sizes(side, beta, hedge_scale)
        self._submit(self.order_target_size(data=self.asset_a, target=target_a))
        self._submit(self.order_target_size(data=self.asset_b, target=target_b))
        self.current_spread_side = 1 if side > 0 else -1

    def _close_all(self):
        pos_a = self.getposition(self.asset_a).size
        pos_b = self.getposition(self.asset_b).size
        if pos_a:
            self._submit(self.close(data=self.asset_a))
            if pos_a > 0:
                self.sell_count += 1
            else:
                self.buy_count += 1
        if pos_b:
            self._submit(self.close(data=self.asset_b))
            if pos_b > 0:
                self.sell_count += 1
            else:
                self.buy_count += 1
        self.current_spread_side = 0

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        regime = float(self.signal.regime[0]) if self.signal.regime[0] == self.signal.regime[0] else None
        if regime is not None:
            if regime >= 2.0:
                self.hold_regime_days += 1
            elif regime <= 0.0:
                self.break_regime_days += 1
            else:
                self.neutral_regime_days += 1
        if self.order_refs:
            return
        beta = float(self.signal.hedge_ratio[0]) if self.signal.hedge_ratio[0] == self.signal.hedge_ratio[0] else None
        zscore = float(self.signal.zscore[0]) if self.signal.zscore[0] == self.signal.zscore[0] else None
        hedge_scale = float(self.signal.hedge_scale[0]) if self.signal.hedge_scale[0] == self.signal.hedge_scale[0] else 0.0
        corr_break = float(self.signal.corr_break[0]) > 0.5
        if beta is None or zscore is None:
            return
        desired_side = 1 if zscore <= -float(self.p.entry_zscore) else -1 if zscore >= float(self.p.entry_zscore) else 0
        if not self._position_open():
            if corr_break or desired_side == 0:
                return
            if desired_side > 0:
                self.buy_count += 1
                self.sell_count += 1
            else:
                self.sell_count += 1
                self.buy_count += 1
            self._rebalance_pair(desired_side, beta, hedge_scale)
            return
        if corr_break or abs(zscore) <= float(self.p.exit_zscore) or abs(zscore) >= float(self.p.stop_zscore):
            self._close_all()
            return
        if desired_side != 0 and desired_side != self.current_spread_side:
            self._close_all()
            return
        self._rebalance_pair(self.current_spread_side, beta, hedge_scale)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
