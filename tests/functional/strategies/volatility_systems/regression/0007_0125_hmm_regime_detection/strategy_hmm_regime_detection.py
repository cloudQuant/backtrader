from __future__ import absolute_import, division, print_function, unicode_literals

import io
import warnings

import backtrader as bt
from hmmlearn.hmm import GaussianHMM
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')


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


def _standardize(train_values, predict_values):
    mean = np.nanmean(train_values, axis=0)
    std = np.nanstd(train_values, axis=0)
    std = np.where(std == 0, 1.0, std)
    return (train_values - mean) / std, (predict_values - mean) / std


def _label_states(model, features_std):
    hidden_states = model.predict(features_std)
    labels = {}
    state_stats = {}
    for state in range(model.n_components):
        mask = hidden_states == state
        if not np.any(mask):
            state_stats[state] = {'ret_mean': -999.0, 'vol_mean': 999.0}
            continue
        subset = features_std[mask]
        state_stats[state] = {
            'ret_mean': float(np.mean(subset[:, 0])),
            'vol_mean': float(np.mean(subset[:, 1])),
        }
    bull_state = max(state_stats, key=lambda s: state_stats[s]['ret_mean'])
    bear_state = min(state_stats, key=lambda s: state_stats[s]['ret_mean'])
    for state in state_stats:
        if state == bull_state:
            labels[state] = 'BULL'
        elif state == bear_state:
            labels[state] = 'BEAR'
        else:
            labels[state] = 'NEUTRAL'
    return labels


def prepare_hmm_regime_features(df, params):
    out = df.copy()
    train_window = int(params.get('train_window', 252))
    retrain_interval = int(params.get('retrain_interval', 63))
    volatility_window = int(params.get('volatility_window', 20))
    momentum_window = int(params.get('momentum_window', 60))
    smoothing_window = int(params.get('smoothing_window', 5))
    n_states = int(params.get('n_states', 3))
    n_iter = int(params.get('n_iter', 300))
    covariance_type = str(params.get('covariance_type', 'full'))
    confidence_threshold = float(params.get('confidence_threshold', 0.55))

    out['log_return'] = np.log(out['close'] / out['close'].shift(1))
    out['volatility'] = out['log_return'].rolling(volatility_window).std() * np.sqrt(252.0)
    out['momentum'] = out['close'].pct_change(momentum_window)
    feature_frame = out[['log_return', 'volatility', 'momentum']].copy()

    predicted_state = [np.nan] * len(out)
    regime_score = [np.nan] * len(out)
    state_confidence = [np.nan] * len(out)
    persistence_prob = [np.nan] * len(out)
    target_exposure = [0.0] * len(out)
    retrain_point = [0.0] * len(out)
    bull_signal = [0.0] * len(out)
    bear_signal = [0.0] * len(out)
    neutral_signal = [1.0] * len(out)

    last_model = None
    last_labels = None
    last_train_idx = None
    recent_states = []

    for idx in range(len(out)):
        start = idx - train_window
        if start < 0:
            continue
        train_slice = feature_frame.iloc[start:idx].dropna()
        current_row = feature_frame.iloc[idx:idx + 1].dropna()
        if len(train_slice) < train_window or current_row.empty:
            continue

        should_retrain = last_model is None or last_train_idx is None or (idx - last_train_idx) >= retrain_interval
        if should_retrain:
            train_values = train_slice.values.astype(float)
            predict_values = np.vstack([train_values, current_row.values.astype(float)])
            train_std, predict_std = _standardize(train_values, predict_values)
            model = GaussianHMM(
                n_components=n_states,
                covariance_type=covariance_type,
                n_iter=n_iter,
                random_state=42,
            )
            try:
                model.fit(train_std)
                labels = _label_states(model, train_std)
                last_model = model
                last_labels = labels
                last_train_idx = idx
                retrain_point[idx] = 1.0
                recent_states = []
            except Exception:
                continue

        if last_model is None or last_labels is None:
            continue

        train_values = train_slice.values.astype(float)
        predict_values = np.vstack([train_values, current_row.values.astype(float)])
        _, predict_std = _standardize(train_values, predict_values)
        try:
            state_seq = last_model.predict(predict_std)
            proba = last_model.predict_proba(predict_std)
        except Exception:
            continue

        current_state = int(state_seq[-1])
        current_label = last_labels.get(current_state, 'NEUTRAL')
        current_confidence = float(proba[-1, current_state])
        persistence = float(last_model.transmat_[current_state, current_state])
        recent_states.append(current_state)
        if len(recent_states) > smoothing_window:
            recent_states = recent_states[-smoothing_window:]
        consistent = len(recent_states) >= smoothing_window and all(s == current_state for s in recent_states[-smoothing_window:])

        signed_target = 0.0
        if current_confidence >= confidence_threshold and consistent:
            if current_label == 'BULL':
                signed_target = min(1.0, 1.0 * current_confidence)
                bull_signal[idx] = 1.0
                neutral_signal[idx] = 0.0
            elif current_label == 'BEAR':
                signed_target = max(-0.5, -0.5 * current_confidence)
                bear_signal[idx] = 1.0
                neutral_signal[idx] = 0.0
            else:
                neutral_signal[idx] = 1.0
        else:
            current_label = 'NEUTRAL'
            neutral_signal[idx] = 1.0

        predicted_state[idx] = current_state
        regime_score[idx] = 1.0 if current_label == 'BULL' else (-1.0 if current_label == 'BEAR' else 0.0)
        state_confidence[idx] = current_confidence
        persistence_prob[idx] = persistence
        target_exposure[idx] = signed_target

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

    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'predicted_state', 'regime_score', 'state_confidence', 'persistence_prob',
        'target_exposure', 'retrain_point', 'bull_signal', 'bear_signal', 'neutral_signal', 'signal_change',
    ]
    return out[columns].copy().dropna()


class HMMRegimeFeed(bt.feeds.PandasData):
    lines = (
        'predicted_state', 'regime_score', 'state_confidence', 'persistence_prob',
        'target_exposure', 'retrain_point', 'bull_signal', 'bear_signal', 'neutral_signal', 'signal_change',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('predicted_state', 6), ('regime_score', 7), ('state_confidence', 8), ('persistence_prob', 9),
        ('target_exposure', 10), ('retrain_point', 11), ('bull_signal', 12), ('bear_signal', 13), ('neutral_signal', 14), ('signal_change', 15),
    )


class HMMRegimeStrategy(bt.Strategy):
    params = dict(
        n_states=3,
        train_window=252,
        retrain_interval=63,
        volatility_window=20,
        momentum_window=60,
        smoothing_window=5,
        n_iter=300,
        covariance_type='full',
        confidence_threshold=0.55,
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
