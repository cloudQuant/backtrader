from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans


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


def _standardize(train_values, predict_values):
    mean = np.nanmean(train_values, axis=0)
    std = np.nanstd(train_values, axis=0)
    std = np.where(std == 0, 1.0, std)
    return (train_values - mean) / std, (predict_values - mean) / std


def _softmax(values):
    shifted = values - np.max(values)
    exps = np.exp(shifted)
    denom = np.sum(exps)
    if denom <= 0:
        return np.ones_like(values) / len(values)
    return exps / denom


def _build_feature_frame(out, params):
    vol_window = int(params.get('volatility_window', 21))
    momentum_window = int(params.get('momentum_window', 63))
    feature_frame = pd.DataFrame(index=out.index)
    feature_frame['ret_1'] = out['close'].pct_change(1)
    feature_frame['ret_5'] = out['close'].pct_change(5)
    feature_frame['volatility'] = out['close'].pct_change().rolling(vol_window).std() * np.sqrt(252.0)
    feature_frame['momentum'] = out['close'].pct_change(momentum_window)
    return feature_frame


def _label_states(train_states, train_features, n_states):
    stats = {}
    for state in range(n_states):
        subset = train_features[train_states == state]
        if len(subset) == 0:
            stats[state] = {'mean': -999.0, 'volatility': 999.0}
            continue
        stats[state] = {
            'mean': float(np.nanmean(subset[:, 0])),
            'volatility': float(np.nanmean(subset[:, 2])) if subset.shape[1] > 2 else 999.0,
        }
    ordered = sorted(stats.items(), key=lambda item: item[1]['mean'])
    labels = {state: 'NEUTRAL' for state in stats}
    if ordered:
        labels[ordered[0][0]] = 'BEAR'
        labels[ordered[-1][0]] = 'BULL'
    if n_states > 2 and len(ordered) > 2:
        for state, _ in ordered[1:-1]:
            labels[state] = 'NEUTRAL'
    return labels, stats


def _estimate_transition(states, n_states):
    transition = np.zeros((n_states, n_states), dtype=float)
    for idx in range(len(states) - 1):
        from_state = int(states[idx])
        to_state = int(states[idx + 1])
        transition[from_state, to_state] += 1.0
    for idx in range(n_states):
        row_sum = transition[idx].sum()
        if row_sum > 0:
            transition[idx] /= row_sum
        else:
            transition[idx, idx] = 1.0
    return transition


def prepare_regime_switching_features(df, params):
    out = df.copy()
    train_window = int(params.get('train_window', 252))
    retrain_interval = int(params.get('retrain_interval', 21))
    n_states = int(params.get('n_states', 2))
    min_state_prob = float(params.get('min_state_prob', 0.55))
    min_persistence_prob = float(params.get('min_persistence_prob', 0.55))
    bull_volatility_threshold = float(params.get('bull_volatility_threshold', 0.018))
    neutral_exposure = float(params.get('neutral_exposure', 0.35))
    short_exposure = float(params.get('short_exposure', 0.50))
    allow_short = bool(params.get('allow_short', True))
    random_state = int(params.get('random_state', 42))

    feature_frame = _build_feature_frame(out, params)
    predicted_state = [np.nan] * len(out)
    regime_score = [np.nan] * len(out)
    state_confidence = [np.nan] * len(out)
    persistence_prob = [np.nan] * len(out)
    target_exposure = [0.0] * len(out)
    retrain_point = [0.0] * len(out)
    bull_signal = [0.0] * len(out)
    bear_signal = [0.0] * len(out)
    neutral_signal = [1.0] * len(out)
    state_mean = [np.nan] * len(out)
    state_volatility = [np.nan] * len(out)

    last_model = None
    last_labels = None
    last_transition = None
    last_stats = None
    last_train_idx = None

    for idx in range(len(out)):
        start = idx - train_window
        if start < 0:
            continue
        train_slice = feature_frame.iloc[start:idx].dropna()
        current_row = feature_frame.iloc[idx:idx + 1].dropna()
        if len(train_slice) < train_window or current_row.empty:
            continue
        should_retrain = last_model is None or last_train_idx is None or (idx - last_train_idx) >= retrain_interval
        train_values = train_slice.values.astype(float)
        predict_values = np.vstack([train_values, current_row.values.astype(float)])
        train_std, predict_std = _standardize(train_values, predict_values)
        if should_retrain:
            model = KMeans(n_clusters=n_states, random_state=random_state, n_init=20)
            train_states = model.fit_predict(train_std)
            labels, stats = _label_states(train_states, train_values, n_states)
            transition = _estimate_transition(train_states, n_states)
            last_model = model
            last_labels = labels
            last_stats = stats
            last_transition = transition
            last_train_idx = idx
            retrain_point[idx] = 1.0
        if last_model is None or last_labels is None or last_transition is None or last_stats is None:
            continue
        current_std = predict_std[-1:]
        current_state = int(last_model.predict(current_std)[0])
        distances = last_model.transform(current_std)[0]
        probs = _softmax(-distances)
        confidence = float(probs[current_state])
        persistence = float(last_transition[current_state, current_state])
        label = last_labels.get(current_state, 'NEUTRAL')
        stats = last_stats.get(current_state, {'mean': 0.0, 'volatility': np.nan})
        exposure = 0.0
        if confidence >= min_state_prob and persistence >= min_persistence_prob:
            if label == 'BULL':
                exposure = 1.0 if float(stats.get('volatility', np.nan)) <= bull_volatility_threshold else neutral_exposure
                bull_signal[idx] = 1.0
                neutral_signal[idx] = 0.0
            elif label == 'BEAR':
                exposure = -short_exposure if allow_short else 0.0
                if allow_short:
                    bear_signal[idx] = 1.0
                    neutral_signal[idx] = 0.0
            else:
                exposure = neutral_exposure
        predicted_state[idx] = current_state
        regime_score[idx] = 1.0 if label == 'BULL' else (-1.0 if label == 'BEAR' else 0.0)
        state_confidence[idx] = confidence
        persistence_prob[idx] = persistence
        target_exposure[idx] = exposure
        state_mean[idx] = float(stats.get('mean', np.nan))
        state_volatility[idx] = float(stats.get('volatility', np.nan))

    out['predicted_state'] = pd.Series(predicted_state, index=out.index, dtype='float64')
    out['regime_score'] = pd.Series(regime_score, index=out.index, dtype='float64')
    out['state_confidence'] = pd.Series(state_confidence, index=out.index, dtype='float64')
    out['persistence_prob'] = pd.Series(persistence_prob, index=out.index, dtype='float64')
    out['target_exposure'] = pd.Series(target_exposure, index=out.index, dtype='float64')
    out['retrain_point'] = pd.Series(retrain_point, index=out.index, dtype='float64')
    out['bull_signal'] = pd.Series(bull_signal, index=out.index, dtype='float64')
    out['bear_signal'] = pd.Series(bear_signal, index=out.index, dtype='float64')
    out['neutral_signal'] = pd.Series(neutral_signal, index=out.index, dtype='float64')
    out['signal_change'] = out['target_exposure'].ne(out['target_exposure'].shift(1)).astype(float)
    out['state_mean'] = pd.Series(state_mean, index=out.index, dtype='float64')
    out['state_volatility'] = pd.Series(state_volatility, index=out.index, dtype='float64')
    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'predicted_state', 'regime_score', 'state_confidence', 'persistence_prob',
        'target_exposure', 'retrain_point', 'bull_signal', 'bear_signal', 'neutral_signal',
        'signal_change', 'state_mean', 'state_volatility',
    ]
    return out[columns].copy().dropna()


class RegimeSwitchingFeed(bt.feeds.PandasData):
    lines = (
        'predicted_state', 'regime_score', 'state_confidence', 'persistence_prob',
        'target_exposure', 'retrain_point', 'bull_signal', 'bear_signal', 'neutral_signal',
        'signal_change', 'state_mean', 'state_volatility',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('predicted_state', 6), ('regime_score', 7), ('state_confidence', 8), ('persistence_prob', 9),
        ('target_exposure', 10), ('retrain_point', 11), ('bull_signal', 12), ('bear_signal', 13), ('neutral_signal', 14),
        ('signal_change', 15), ('state_mean', 16), ('state_volatility', 17),
    )


class RegimeSwitchingModelingStrategy(bt.Strategy):
    params = dict(
        n_states=2,
        train_window=252,
        retrain_interval=21,
        volatility_window=21,
        momentum_window=63,
        min_state_prob=0.55,
        min_persistence_prob=0.55,
        bull_volatility_threshold=0.018,
        neutral_exposure=0.35,
        short_exposure=0.5,
        allow_short=True,
        random_state=42,
    )

    def __init__(self):
        self.bar_num = 0
        self.pending_order = None
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.retrain_count = 0
        self.signal_change_count = 0
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if float(self.data.retrain_point[0]) > 0.5:
            self.retrain_count += 1
        if self.pending_order is not None:
            return
        if float(self.data.signal_change[0]) <= 0.5:
            return
        self.signal_change_count += 1
        self.pending_order = self.order_target_percent(target=float(self.data.target_exposure[0]))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
