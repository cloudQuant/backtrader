from __future__ import absolute_import, division, print_function, unicode_literals

import io
import warnings

import backtrader as bt
from hmmlearn.hmm import GaussianHMM
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings('ignore')


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


def _standardize(train_values, predict_values):
    mean = np.nanmean(train_values, axis=0)
    std = np.nanstd(train_values, axis=0)
    std = np.where(std == 0, 1.0, std)
    return (train_values - mean) / std, (predict_values - mean) / std


def _build_feature_table(out, params):
    returns_window = int(params.get('returns_window', 5))
    volatility_window = int(params.get('volatility_window', 21))
    momentum_window = int(params.get('momentum_window', 10))
    feature_df = pd.DataFrame(index=out.index)
    feature_df['ret_1'] = out['close'].pct_change(1)
    feature_df[f'ret_{returns_window}'] = out['close'].pct_change(returns_window)
    feature_df['ret_10'] = out['close'].pct_change(10)
    feature_df['ret_20'] = out['close'].pct_change(20)
    feature_df['volatility'] = out['close'].pct_change().rolling(volatility_window).std() * np.sqrt(252.0)
    feature_df['momentum'] = out['close'].pct_change(momentum_window)
    feature_df['volume_change'] = out['volume'].pct_change(5).replace([np.inf, -np.inf], np.nan)
    feature_df['range_pct'] = (out['high'] - out['low']) / out['close'].replace(0, np.nan)
    feature_df['close_vs_ma20'] = out['close'] / out['close'].rolling(20).mean() - 1.0
    feature_df['close_vs_ma50'] = out['close'] / out['close'].rolling(50).mean() - 1.0
    return feature_df


def _label_states(train_states, hmm_input_std):
    state_stats = {}
    for state in np.unique(train_states):
        mask = train_states == state
        subset = hmm_input_std[mask]
        state_stats[int(state)] = {
            'ret_mean': float(np.mean(subset[:, 0])) if len(subset) else -999.0,
            'vol_mean': float(np.mean(subset[:, 1])) if len(subset) > 0 and subset.shape[1] > 1 else 999.0,
        }
    bull_state = max(state_stats, key=lambda s: state_stats[s]['ret_mean'])
    bear_state = min(state_stats, key=lambda s: state_stats[s]['ret_mean'])
    labels = {}
    for state in state_stats:
        if state == bull_state:
            labels[state] = 'BULL'
        elif state == bear_state:
            labels[state] = 'BEAR'
        else:
            labels[state] = 'NEUTRAL'
    return labels


def prepare_hmm_rf_features(df, params):
    out = df.copy()
    train_window = int(params.get('train_window', 252))
    retrain_interval = int(params.get('retrain_interval', 21))
    n_states = int(params.get('n_states', 3))
    covariance_type = str(params.get('covariance_type', 'full'))
    n_iter = int(params.get('n_iter', 100))
    n_estimators = int(params.get('n_estimators', 200))
    max_depth = int(params.get('max_depth', 8))
    min_samples_split = int(params.get('min_samples_split', 10))
    signal_threshold = float(params.get('signal_threshold', 0.60))
    base_target_percent = float(params.get('base_target_percent', 0.20))
    max_target_percent = float(params.get('max_target_percent', 0.75))
    random_state = int(params.get('random_state', 42))

    feature_df = _build_feature_table(out, params)
    hmm_df = pd.DataFrame(index=out.index)
    hmm_df['returns'] = feature_df['ret_1']
    hmm_df['volatility'] = feature_df['volatility']
    hmm_df['volume_change'] = feature_df['volume_change']
    target = (out['close'].shift(-1) > out['close']).astype(float)

    predicted_state = [np.nan] * len(out)
    regime_score = [np.nan] * len(out)
    state_confidence = [np.nan] * len(out)
    up_probability = [np.nan] * len(out)
    signal_code = [0.0] * len(out)
    target_percent = [0.0] * len(out)
    retrain_point = [0.0] * len(out)
    bull_signal = [0.0] * len(out)
    bear_signal = [0.0] * len(out)
    neutral_signal = [1.0] * len(out)

    last_hmm = None
    last_state_labels = None
    last_rf_models = {}
    last_train_idx = None

    for idx in range(train_window, len(out) - 1):
        train_slice = slice(idx - train_window, idx)
        hmm_train = hmm_df.iloc[train_slice].copy()
        feat_train = feature_df.iloc[train_slice].copy()
        target_train = target.iloc[train_slice].copy()
        current_hmm = hmm_df.iloc[idx:idx + 1].copy()
        current_feat = feature_df.iloc[idx:idx + 1].copy()
        if hmm_train.isna().any().any() or feat_train.isna().any().any() or current_hmm.isna().any().any() or current_feat.isna().any().any():
            continue
        should_retrain = last_hmm is None or last_train_idx is None or (idx - last_train_idx) >= retrain_interval
        if should_retrain:
            train_values = hmm_train.values.astype(float)
            predict_values = np.vstack([train_values, current_hmm.values.astype(float)])
            hmm_train_std, predict_std = _standardize(train_values, predict_values)
            hmm_model = GaussianHMM(
                n_components=n_states,
                covariance_type=covariance_type,
                n_iter=n_iter,
                random_state=random_state,
            )
            try:
                hmm_model.fit(hmm_train_std)
                train_states = hmm_model.predict(hmm_train_std)
                state_labels = _label_states(train_states, hmm_train_std)
                rf_models = {}
                for state in range(n_states):
                    state_mask = train_states == state
                    if np.sum(state_mask) < max(40, min_samples_split * 2):
                        continue
                    X_state = feat_train.iloc[state_mask].copy()
                    y_state = target_train.iloc[state_mask].copy()
                    valid = ~(X_state.isna().any(axis=1) | y_state.isna())
                    X_state = X_state.loc[valid]
                    y_state = y_state.loc[valid]
                    if len(X_state) < max(30, min_samples_split * 2):
                        continue
                    if y_state.nunique() < 2:
                        continue
                    rf = RandomForestClassifier(
                        n_estimators=n_estimators,
                        max_depth=max_depth,
                        min_samples_split=min_samples_split,
                        random_state=random_state,
                    )
                    rf.fit(X_state.values, y_state.astype(int).values)
                    rf_models[state] = rf
                last_hmm = hmm_model
                last_state_labels = state_labels
                last_rf_models = rf_models
                last_train_idx = idx
                retrain_point[idx] = 1.0
            except Exception:
                continue
        if last_hmm is None or not last_rf_models:
            continue
        train_values = hmm_train.values.astype(float)
        predict_values = np.vstack([train_values, current_hmm.values.astype(float)])
        _, predict_std = _standardize(train_values, predict_values)
        try:
            seq = last_hmm.predict(predict_std)
            proba = last_hmm.predict_proba(predict_std)
        except Exception:
            continue
        current_state = int(seq[-1])
        current_confidence = float(proba[-1, current_state])
        current_label = last_state_labels.get(current_state, 'NEUTRAL')
        current_rf = last_rf_models.get(current_state)
        if current_rf is None:
            continue
        try:
            rf_proba = current_rf.predict_proba(current_feat.values)[0]
        except Exception:
            continue
        class_index = list(current_rf.classes_).index(1) if 1 in current_rf.classes_ else None
        if class_index is None:
            continue
        prob_up = float(rf_proba[class_index])
        edge = abs(prob_up - 0.5) * 2.0
        scaled_target = min(max_target_percent, base_target_percent + edge * (max_target_percent - base_target_percent))
        predicted_state[idx] = current_state
        state_confidence[idx] = current_confidence
        up_probability[idx] = prob_up
        if prob_up > signal_threshold:
            signal_code[idx] = 1.0
            bull_signal[idx] = 1.0
            bear_signal[idx] = 0.0
            neutral_signal[idx] = 0.0
            target_percent[idx] = scaled_target
            regime_score[idx] = 1.0 if current_label == 'BULL' else 0.5
        elif prob_up < (1.0 - signal_threshold):
            signal_code[idx] = -1.0
            bull_signal[idx] = 0.0
            bear_signal[idx] = 1.0
            neutral_signal[idx] = 0.0
            target_percent[idx] = scaled_target
            regime_score[idx] = -1.0 if current_label == 'BEAR' else -0.5
        else:
            signal_code[idx] = 0.0
            bull_signal[idx] = 0.0
            bear_signal[idx] = 0.0
            neutral_signal[idx] = 1.0
            target_percent[idx] = 0.0
            regime_score[idx] = 0.0

    out['predicted_state'] = pd.Series(predicted_state, index=out.index, dtype='float64')
    out['regime_score'] = pd.Series(regime_score, index=out.index, dtype='float64')
    out['state_confidence'] = pd.Series(state_confidence, index=out.index, dtype='float64')
    out['up_probability'] = pd.Series(up_probability, index=out.index, dtype='float64')
    out['signal_code'] = pd.Series(signal_code, index=out.index, dtype='float64')
    out['target_percent'] = pd.Series(target_percent, index=out.index, dtype='float64')
    out['retrain_point'] = pd.Series(retrain_point, index=out.index, dtype='float64')
    out['bull_signal'] = pd.Series(bull_signal, index=out.index, dtype='float64')
    out['bear_signal'] = pd.Series(bear_signal, index=out.index, dtype='float64')
    out['neutral_signal'] = pd.Series(neutral_signal, index=out.index, dtype='float64')
    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'predicted_state', 'regime_score', 'state_confidence', 'up_probability', 'signal_code', 'target_percent',
        'retrain_point', 'bull_signal', 'bear_signal', 'neutral_signal',
    ]
    return out[columns].copy().dropna()


class Mt5HMMRFFeed(bt.feeds.PandasData):
    lines = ('predicted_state', 'regime_score', 'state_confidence', 'up_probability', 'signal_code', 'target_percent', 'retrain_point', 'bull_signal', 'bear_signal', 'neutral_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('predicted_state', 6), ('regime_score', 7), ('state_confidence', 8), ('up_probability', 9), ('signal_code', 10), ('target_percent', 11), ('retrain_point', 12), ('bull_signal', 13), ('bear_signal', 14), ('neutral_signal', 15),
    )


class HMMRandomForestStrategy(bt.Strategy):
    params = dict(
        train_window=252,
        retrain_interval=21,
        n_states=3,
        covariance_type='full',
        n_iter=100,
        n_estimators=200,
        max_depth=8,
        min_samples_split=10,
        signal_threshold=0.6,
        base_target_percent=0.2,
        max_target_percent=0.75,
        returns_window=5,
        volatility_window=21,
        momentum_window=10,
        random_state=42,
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
        self.retrain_count = 0
        self.pending_order = None
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
        if float(self.data.retrain_point[0]) > 0.5:
            self.retrain_count += 1
        if self.pending_order is not None:
            return
        bull_signal = float(self.data.bull_signal[0]) > 0.5
        bear_signal = float(self.data.bear_signal[0]) > 0.5
        neutral_signal = float(self.data.neutral_signal[0]) > 0.5
        target_percent = float(self.data.target_percent[0])
        target_size = self._get_position_size(target_notional_pct=target_percent)
        if self.position:
            if self.position.size > 0 and (neutral_signal or bear_signal or target_size <= 0):
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.position.size < 0 and (neutral_signal or bull_signal or target_size <= 0):
                self.cover_count += 1
                self.pending_order = self.close()
                return
            return
        if target_size <= 0:
            return
        if bull_signal:
            self.buy_count += 1
            self.pending_order = self.buy(size=target_size)
            return
        if bear_signal:
            self.short_count += 1
            self.pending_order = self.sell(size=target_size)

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
