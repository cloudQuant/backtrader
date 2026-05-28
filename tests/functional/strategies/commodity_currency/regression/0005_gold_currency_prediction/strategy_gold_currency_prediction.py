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


def rolling_linear_forecast(feature_matrix, target_series, train_window):
    predictions = np.full(len(target_series), np.nan, dtype=float)
    confidences = np.full(len(target_series), np.nan, dtype=float)
    for idx in range(train_window, len(target_series) - 1):
        x_train = feature_matrix.iloc[idx - train_window:idx].values
        y_train = target_series.iloc[idx - train_window:idx].values
        if np.isnan(x_train).any() or np.isnan(y_train).any():
            continue
        design_train = np.column_stack([np.ones(len(x_train)), x_train])
        coeffs, _, _, _ = np.linalg.lstsq(design_train, y_train, rcond=None)
        resid = y_train - design_train @ coeffs
        resid_std = np.std(resid)
        x_now = feature_matrix.iloc[idx].values
        if np.isnan(x_now).any():
            continue
        prediction = float(np.r_[1.0, x_now] @ coeffs)
        predictions[idx] = prediction
        confidences[idx] = min(1.0, abs(prediction) / max(resid_std, 1e-6))
    return predictions, confidences


def prepare_currency_prediction_data(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    asset_frames = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    returns = pd.DataFrame(index=common_index)
    returns['gold_ret'] = asset_frames['XAUUSD']['close'].pct_change()
    returns['dxy_ret_1'] = asset_frames['DXYN']['close'].pct_change(1)
    returns['dxy_ret_5'] = asset_frames['DXYN']['close'].pct_change(5)
    returns['dxy_ret_20'] = asset_frames['DXYN']['close'].pct_change(20)
    returns['eur_ret_1'] = asset_frames['EURUSD']['close'].pct_change(1)
    returns['eur_ret_5'] = asset_frames['EURUSD']['close'].pct_change(5)
    returns['eur_ret_20'] = asset_frames['EURUSD']['close'].pct_change(20)
    returns['jpy_ret_1'] = asset_frames['USDJPY']['close'].pct_change(1)
    returns['jpy_ret_5'] = asset_frames['USDJPY']['close'].pct_change(5)
    returns['jpy_ret_20'] = asset_frames['USDJPY']['close'].pct_change(20)
    feature_cols = [col for col in returns.columns if col != 'gold_ret']
    train_window = int(params.get('train_window', 252))
    predictions, confidences = rolling_linear_forecast(returns[feature_cols], returns['gold_ret'], train_window)
    out = asset_frames['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    out['predicted_return'] = predictions
    out['prediction_confidence'] = confidences
    out['dxy_confirm'] = (returns['dxy_ret_1'] < 0).astype(float)
    out['eur_confirm'] = (returns['eur_ret_1'] > 0).astype(float)
    threshold = float(params.get('confidence_threshold', 0.6))
    out['entry_signal'] = ((out['predicted_return'] > 0) & (out['prediction_confidence'] >= threshold) & ((out['dxy_confirm'] > 0) | (out['eur_confirm'] > 0))).astype(float)
    out['exit_signal'] = ((out['predicted_return'] <= 0) | (out['prediction_confidence'] < threshold)).astype(float)
    out['target_pct'] = (float(params.get('base_position_pct', 0.03)) * out['prediction_confidence'].clip(lower=0.0, upper=float(params.get('max_position_pct', 0.05)) / float(params.get('base_position_pct', 0.03)))).clip(upper=float(params.get('max_position_pct', 0.05)))
    return out.dropna(subset=['predicted_return', 'prediction_confidence'])


class GoldCurrencyPredictionFeed(bt.feeds.PandasData):
    lines = ('predicted_return', 'prediction_confidence', 'dxy_confirm', 'eur_confirm', 'entry_signal', 'exit_signal', 'target_pct')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('predicted_return', 6), ('prediction_confidence', 7), ('dxy_confirm', 8), ('eur_confirm', 9), ('entry_signal', 10), ('exit_signal', 11), ('target_pct', 12),
    )


class GoldCurrencyPredictionStrategy(bt.Strategy):
    params = dict(
        stop_loss_pct=0.03,
        train_window=252,
        confidence_threshold=0.6,
        base_position_pct=0.03,
        max_position_pct=0.05,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_price = None
        self.stop_price = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        close = float(self.data.close[0])
        low = float(self.data.low[0])
        if self.position:
            if self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if float(self.data.exit_signal[0]) > 0.5:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return
        if float(self.data.entry_signal[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.order_target_percent(target=float(self.data.target_pct[0]))
            self.entry_price = close
            self.stop_price = close * (1.0 - float(self.p.stop_loss_pct))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None
