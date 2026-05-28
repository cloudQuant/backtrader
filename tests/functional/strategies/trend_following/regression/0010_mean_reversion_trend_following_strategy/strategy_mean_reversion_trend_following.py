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


def prepare_combined_features(df, params):
    out = df.copy()
    mr_lookback = int(params.get('mr_lookback', 15))
    mr_entry_threshold = float(params.get('mr_entry_threshold', 1.5))
    mr_exit_threshold = float(params.get('mr_exit_threshold', 0.5))
    tf_fast_ma = int(params.get('tf_fast_ma', 50))
    tf_slow_ma = int(params.get('tf_slow_ma', 200))
    mr_weight = float(params.get('mr_weight', 0.4))
    tf_weight = float(params.get('tf_weight', 0.6))
    max_target_percent = float(params.get('max_target_percent', 1.0))

    rolling_mean = out['close'].rolling(mr_lookback).mean()
    rolling_std = out['close'].rolling(mr_lookback).std()
    zscore = (out['close'] - rolling_mean) / rolling_std.replace(0, np.nan)
    mr_signal = np.where(zscore > mr_entry_threshold, -1.0, np.where(zscore < -mr_entry_threshold, 1.0, np.where(np.abs(zscore) < mr_exit_threshold, 0.0, np.nan)))
    mr_signal = pd.Series(mr_signal, index=out.index, dtype='float64').ffill().fillna(0.0)

    ma_fast = out['close'].rolling(tf_fast_ma).mean()
    ma_slow = out['close'].rolling(tf_slow_ma).mean()
    tf_signal = np.where(ma_fast > ma_slow, 1.0, np.where(ma_fast < ma_slow, -1.0, 0.0))
    tf_signal = pd.Series(tf_signal, index=out.index, dtype='float64')

    combined_signal = mr_weight * mr_signal + tf_weight * tf_signal
    target_percent = combined_signal.clip(lower=-max_target_percent, upper=max_target_percent)

    out['zscore'] = zscore.astype(float)
    out['mr_signal'] = mr_signal.astype(float)
    out['ma_fast'] = ma_fast.astype(float)
    out['ma_slow'] = ma_slow.astype(float)
    out['tf_signal'] = tf_signal.astype(float)
    out['combined_signal'] = combined_signal.astype(float)
    out['target_percent'] = target_percent.astype(float)
    return out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'zscore', 'mr_signal', 'ma_fast', 'ma_slow', 'tf_signal', 'combined_signal', 'target_percent',
    ]].dropna().copy()


class CombinedSignalFeed(bt.feeds.PandasData):
    lines = ('zscore', 'mr_signal', 'ma_fast', 'ma_slow', 'tf_signal', 'combined_signal', 'target_percent')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('zscore', 6), ('mr_signal', 7), ('ma_fast', 8), ('ma_slow', 9), ('tf_signal', 10), ('combined_signal', 11), ('target_percent', 12),
    )


class MeanReversionTrendFollowingStrategy(bt.Strategy):
    params = dict(
        rebalance_tolerance=0.05,
        mr_lookback=15,
        mr_entry_threshold=1.5,
        mr_exit_threshold=0.5,
        tf_fast_ma=50,
        tf_slow_ma=200,
        mr_weight=0.4,
        tf_weight=0.6,
        max_target_percent=1.0,
        commission_pct=0.0005,
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
        self.long_bias_days = 0
        self.short_bias_days = 0
        self.flat_bias_days = 0

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
        target_percent = float(self.data.target_percent[0])
        if target_percent > 0.05:
            self.long_bias_days += 1
        elif target_percent < -0.05:
            self.short_bias_days += 1
        else:
            self.flat_bias_days += 1
        if self.pending_order is not None:
            return
        current_exposure = self._current_exposure()
        if abs(target_percent - current_exposure) <= float(self.p.rebalance_tolerance):
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
