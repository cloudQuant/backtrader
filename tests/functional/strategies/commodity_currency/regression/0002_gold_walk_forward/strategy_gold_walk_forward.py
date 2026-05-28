from __future__ import absolute_import, division, print_function, unicode_literals

import io
import itertools

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    if bar_shift_minutes:
        parsed = parsed + pd.to_timedelta(int(bar_shift_minutes), unit='m')
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


def _compute_atr(df, window):
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def prepare_walk_forward_features(df, params):
    out = df.copy()
    vol_window = int(params.get('vol_window', 20))
    atr_window = int(params.get('atr_window', 14))
    target_volatility = max(float(params.get('target_volatility', 0.15)), 1e-6)
    base_target_percent = float(params.get('base_target_percent', 0.03))
    max_target_percent = float(params.get('max_target_percent', 0.05))

    out['daily_return'] = out['close'].pct_change()
    out['volatility_20'] = out['daily_return'].rolling(vol_window).std() * np.sqrt(252.0)
    out['atr'] = _compute_atr(out, atr_window)
    out['atr_pct'] = out['atr'] / out['close']
    vol_factor = target_volatility / out['volatility_20'].replace(0, np.nan)
    out['target_percent'] = (base_target_percent * vol_factor).clip(lower=0.0, upper=max_target_percent).fillna(0.0)
    return out


def _build_candidate(df, momentum_window, mean_reversion_window, threshold):
    momentum_return = df['close'] / df['close'].shift(momentum_window) - 1.0
    rolling_mean = df['close'].rolling(mean_reversion_window).mean()
    mean_reversion_edge = (rolling_mean - df['close']) / rolling_mean
    score = momentum_return + mean_reversion_edge
    signal = np.where(score > threshold, 1.0, np.where(score < -threshold, -1.0, 0.0))
    return pd.DataFrame({
        'score': score,
        'signal': pd.Series(signal, index=df.index, dtype='float64'),
    }, index=df.index)


def _annualized_sharpe(returns):
    returns = pd.Series(returns).dropna()
    if returns.empty:
        return -999.0
    std = returns.std(ddof=0)
    if std == 0 or np.isnan(std):
        return -999.0
    return float(np.sqrt(252.0) * returns.mean() / std)


def _evaluate_candidate(feature_df, candidate_df, start_idx, end_idx, commission_estimate):
    window = feature_df.iloc[start_idx:end_idx].copy()
    candidate = candidate_df.iloc[start_idx:end_idx].copy()
    pos = candidate['signal'].shift(1).fillna(0.0)
    target = window['target_percent'].shift(1).fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    strat_returns = pos * target * window['daily_return'].fillna(0.0) - turnover * commission_estimate
    return _annualized_sharpe(strat_returns), strat_returns


def run_walk_forward(feature_df, params):
    train_window = int(params.get('train_window', 252))
    test_window = int(params.get('test_window', 63))
    step_window = int(params.get('step_window', 63))
    commission_estimate = float(params.get('commission_estimate', 0.0002))

    param_grid = list(itertools.product(
        [int(x) for x in params.get('momentum_windows', [10, 20, 30, 60, 120])],
        [int(x) for x in params.get('mean_reversion_windows', [5, 10, 20, 30])],
        [float(x) for x in params.get('signal_thresholds', [0.01, 0.02, 0.03, 0.05])],
    ))

    candidate_cache = {}
    for combo in param_grid:
        candidate_cache[combo] = _build_candidate(feature_df, combo[0], combo[1], combo[2])

    oos_rows = []
    summary_rows = []
    max_required = max(max(params.get('momentum_windows', [120])), max(params.get('mean_reversion_windows', [30])), int(params.get('atr_window', 14)), int(params.get('vol_window', 20)))
    start_anchor = max_required + train_window

    for test_start in range(start_anchor, len(feature_df) - test_window + 1, step_window):
        train_start = test_start - train_window
        train_end = test_start
        test_end = test_start + test_window

        best_combo = None
        best_sharpe = -999.0
        for combo, candidate_df in candidate_cache.items():
            sharpe, _ = _evaluate_candidate(feature_df, candidate_df, train_start, train_end, commission_estimate)
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_combo = combo

        if best_combo is None:
            continue

        candidate_df = candidate_cache[best_combo].iloc[test_start:test_end].copy()
        test_slice = feature_df.iloc[test_start:test_end].copy()
        test_slice['wf_score'] = candidate_df['score']
        test_slice['wf_signal'] = candidate_df['signal']
        test_slice['opt_momentum_window'] = float(best_combo[0])
        test_slice['opt_mean_reversion_window'] = float(best_combo[1])
        test_slice['opt_signal_threshold'] = float(best_combo[2])
        oos_rows.append(test_slice)
        summary_rows.append({
            'train_start': feature_df.index[train_start],
            'train_end': feature_df.index[train_end - 1],
            'test_start': feature_df.index[test_start],
            'test_end': feature_df.index[test_end - 1],
            'momentum_window': best_combo[0],
            'mean_reversion_window': best_combo[1],
            'signal_threshold': best_combo[2],
            'train_sharpe': best_sharpe,
        })

    if not oos_rows:
        raise ValueError('Walk-forward produced no out-of-sample windows')

    oos_df = pd.concat(oos_rows).sort_index()
    oos_df = oos_df[~oos_df.index.duplicated(keep='first')].copy()
    oos_df['long_signal'] = (oos_df['wf_signal'] > 0).astype(float)
    oos_df['short_signal'] = (oos_df['wf_signal'] < 0).astype(float)
    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest', 'daily_return', 'volatility_20', 'atr', 'atr_pct',
        'target_percent', 'wf_score', 'wf_signal', 'opt_momentum_window', 'opt_mean_reversion_window',
        'opt_signal_threshold', 'long_signal', 'short_signal',
    ]
    return oos_df[columns].dropna().copy(), pd.DataFrame(summary_rows)


class Mt5WalkForwardFeed(bt.feeds.PandasData):
    lines = (
        'daily_return', 'volatility_20', 'atr', 'atr_pct', 'target_percent', 'wf_score', 'wf_signal',
        'opt_momentum_window', 'opt_mean_reversion_window', 'opt_signal_threshold', 'long_signal', 'short_signal',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('daily_return', 6), ('volatility_20', 7), ('atr', 8), ('atr_pct', 9), ('target_percent', 10), ('wf_score', 11),
        ('wf_signal', 12), ('opt_momentum_window', 13), ('opt_mean_reversion_window', 14), ('opt_signal_threshold', 15),
        ('long_signal', 16), ('short_signal', 17),
    )


class GoldWalkForwardStrategy(bt.Strategy):
    params = dict(
        atr_stop_multiple=1.5,
        train_window=252,
        test_window=63,
        step_window=63,
        momentum_windows=[10, 20, 30, 60, 120],
        mean_reversion_windows=[5, 10, 20, 30],
        signal_thresholds=[0.01, 0.02, 0.03, 0.05],
        vol_window=20,
        atr_window=14,
        target_volatility=0.15,
        base_target_percent=0.03,
        max_target_percent=0.05,
        commission_estimate=0.0002,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.short_count = 0
        self.cover_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.stop_exit_count = 0
        self.reverse_exit_count = 0
        self.pending_order = None
        self.entry_price = None
        self.entry_side = 0
        self.entry_atr = None
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) / (execution_price * multiplier)
        return max(0.01, round(size, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return

        signal = float(self.data.wf_signal[0])
        target_percent = float(self.data.target_percent[0])
        atr = float(self.data.atr[0]) if self.data.atr[0] == self.data.atr[0] else 0.0
        close_price = float(self.data.close[0])

        if self.position:
            if self.entry_side > 0:
                stop_level = self.entry_price - float(self.p.atr_stop_multiple) * self.entry_atr
                if atr > 0 and close_price <= stop_level:
                    self.sell_count += 1
                    self.stop_exit_count += 1
                    self.pending_order = self.close()
                    return
                if signal < 0:
                    self.sell_count += 1
                    self.reverse_exit_count += 1
                    self.pending_order = self.close()
                    return
            else:
                stop_level = self.entry_price + float(self.p.atr_stop_multiple) * self.entry_atr
                if atr > 0 and close_price >= stop_level:
                    self.cover_count += 1
                    self.stop_exit_count += 1
                    self.pending_order = self.close()
                    return
                if signal > 0:
                    self.cover_count += 1
                    self.reverse_exit_count += 1
                    self.pending_order = self.close()
                    return
            if signal == 0:
                if self.position.size > 0:
                    self.sell_count += 1
                else:
                    self.cover_count += 1
                self.pending_order = self.close()
            return

        size = self._get_position_size(target_notional_pct=target_percent)
        if size <= 0:
            return
        if signal > 0:
            self.buy_count += 1
            self.entry_side = 1
            self.entry_atr = atr
            self.pending_order = self.buy(size=size)
        elif signal < 0:
            self.short_count += 1
            self.entry_side = -1
            self.entry_atr = atr
            self.pending_order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if self.position:
                self.entry_price = float(order.executed.price)
            else:
                self.entry_price = None
                self.entry_side = 0
                self.entry_atr = None
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
