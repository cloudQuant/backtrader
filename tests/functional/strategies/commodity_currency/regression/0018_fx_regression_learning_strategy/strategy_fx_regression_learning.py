from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd
from sklearn.linear_model import Lasso, LinearRegression, Ridge
from sklearn.preprocessing import StandardScaler


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


def _build_model(model_type, alpha):
    model_name = str(model_type).lower()
    if model_name == 'linear':
        return LinearRegression()
    if model_name == 'lasso':
        return Lasso(alpha=float(alpha), max_iter=10000)
    return Ridge(alpha=float(alpha))


def prepare_regression_features(price_df, params):
    out = price_df.copy()
    model_type = params.get('model_type', 'ridge')
    alpha = float(params.get('alpha', 1.0))
    train_window = int(params.get('train_window', 756))
    predict_horizon = int(params.get('predict_horizon', 21))
    signal_threshold = float(params.get('signal_threshold', 0.001))
    max_target_percent = float(params.get('max_target_percent', 1.0))

    close = out['close'].astype(float)
    ret_1 = close.pct_change(1)
    features = pd.DataFrame(index=out.index)
    features['carry_proxy'] = close.pct_change(252) - close.pct_change(63)
    features['momentum_21'] = close.pct_change(21)
    features['momentum_63'] = close.pct_change(63)
    features['momentum_126'] = close.pct_change(126)
    features['value'] = close / close.rolling(252).mean() - 1.0
    features['volatility_21'] = ret_1.rolling(21).std()
    features['volatility_63'] = ret_1.rolling(63).std()
    features['range_21'] = (out['high'] / out['low'] - 1.0).rolling(21).mean()
    target = close.pct_change(predict_horizon).shift(-predict_horizon)

    prediction = pd.Series(np.nan, index=out.index, dtype='float64')
    target_percent = pd.Series(0.0, index=out.index, dtype='float64')
    signal = pd.Series(0.0, index=out.index, dtype='float64')
    coef_l2 = pd.Series(np.nan, index=out.index, dtype='float64')

    for idx in range(train_window, len(features) - predict_horizon):
        train_features = features.iloc[idx - train_window:idx]
        train_target = target.iloc[idx - train_window:idx]
        valid = ~(train_features.isna().any(axis=1) | train_target.isna())
        train_x = train_features.loc[valid]
        train_y = train_target.loc[valid]
        if len(train_x) < max(120, train_window // 3):
            continue
        scaler = StandardScaler()
        model = _build_model(model_type, alpha)
        scaled_x = scaler.fit_transform(train_x)
        model.fit(scaled_x, train_y)
        current_x = features.iloc[[idx]]
        if current_x.isna().any(axis=1).iloc[0]:
            continue
        pred = float(model.predict(scaler.transform(current_x))[0])
        prediction.iloc[idx] = pred
        coef_l2.iloc[idx] = float(np.sqrt(np.sum(np.square(getattr(model, 'coef_', np.zeros(train_x.shape[1]))))))
        if pred > signal_threshold:
            signal.iloc[idx] = 1.0
        elif pred < -signal_threshold:
            signal.iloc[idx] = -1.0
        else:
            signal.iloc[idx] = 0.0
        scaled_strength = 0.0 if signal_threshold <= 0 else min(abs(pred) / signal_threshold, 2.0)
        target_percent.iloc[idx] = max_target_percent * min(scaled_strength / 2.0, 1.0) * signal.iloc[idx]

    out['carry_proxy'] = features['carry_proxy'].astype(float)
    out['momentum_21'] = features['momentum_21'].astype(float)
    out['momentum_63'] = features['momentum_63'].astype(float)
    out['momentum_126'] = features['momentum_126'].astype(float)
    out['value'] = features['value'].astype(float)
    out['volatility_21'] = features['volatility_21'].astype(float)
    out['volatility_63'] = features['volatility_63'].astype(float)
    out['range_21'] = features['range_21'].astype(float)
    out['prediction'] = prediction.astype(float)
    out['signal'] = signal.astype(float)
    out['target_percent'] = target_percent.astype(float)
    out['coef_l2'] = coef_l2.astype(float)
    return out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'carry_proxy', 'momentum_21', 'momentum_63', 'momentum_126', 'value',
        'volatility_21', 'volatility_63', 'range_21', 'prediction', 'signal', 'target_percent', 'coef_l2',
    ]].dropna().copy()


class FXRegressionFeed(bt.feeds.PandasData):
    lines = ('carry_proxy', 'momentum_21', 'momentum_63', 'momentum_126', 'value', 'volatility_21', 'volatility_63', 'range_21', 'prediction', 'signal', 'target_percent', 'coef_l2')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('carry_proxy', 6), ('momentum_21', 7), ('momentum_63', 8), ('momentum_126', 9), ('value', 10), ('volatility_21', 11), ('volatility_63', 12), ('range_21', 13), ('prediction', 14), ('signal', 15), ('target_percent', 16), ('coef_l2', 17),
    )


class FXRegressionLearningStrategy(bt.Strategy):
    params = dict(
        rebalance_interval=5,
        model_type='ridge',
        alpha=1.0,
        train_window=756,
        predict_horizon=21,
        signal_threshold=0.001,
        max_target_percent=1.0,
        commission_pct=0.0002,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.broker_value_series = []
        self.long_signal_days = 0
        self.short_signal_days = 0
        self.neutral_signal_days = 0

    def _current_exposure(self):
        broker_value = float(self.broker.getvalue())
        price = float(self.data.close[0])
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if broker_value <= 0 or price <= 0 or multiplier <= 0:
            return 0.0
        return float(self.position.size) * price * multiplier / broker_value

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        signal_value = float(self.data.signal[0])
        if signal_value > 0.5:
            self.long_signal_days += 1
        elif signal_value < -0.5:
            self.short_signal_days += 1
        else:
            self.neutral_signal_days += 1
        if self.pending_order is not None:
            return
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval)) != 0:
            return
        target_percent = float(self.data.target_percent[0])
        current_exposure = self._current_exposure()
        if abs(target_percent - current_exposure) < 0.02:
            return
        if target_percent > current_exposure:
            self.buy_count += 1
        elif target_percent < current_exposure:
            self.sell_count += 1
        self.pending_order = self.order_target_percent(target=target_percent)

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
