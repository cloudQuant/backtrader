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
    df = df.set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_sentiment_features(df, params):
    out = df.copy()
    sentiment_window = int(params.get('sentiment_window', 30))
    threshold = float(params.get('threshold', 0.15))
    return_z_window = int(params.get('return_z_window', 20))
    volume_window = int(params.get('volume_window', 30))
    volume_impact_weight = float(params.get('volume_impact_weight', 0.5))

    out['returns'] = out['close'].pct_change()
    return_mean = out['returns'].rolling(return_z_window).mean()
    return_std = out['returns'].rolling(return_z_window).std().replace(0, np.nan)
    out['return_z'] = (out['returns'] - return_mean) / return_std
    volume_mean = out['volume'].rolling(volume_window).mean()
    volume_std = out['volume'].rolling(volume_window).std().replace(0, np.nan)
    out['volume_z'] = ((out['volume'] - volume_mean) / volume_std).fillna(0.0)
    impact_multiplier = 1.0 + volume_impact_weight * out['volume_z'].clip(lower=-1.0, upper=3.0)
    out['daily_sentiment_proxy'] = np.tanh(out['return_z'].fillna(0.0) * impact_multiplier.fillna(1.0))
    out['cnri'] = out['daily_sentiment_proxy'].rolling(sentiment_window).mean()
    out['sentiment_signal'] = 0.0
    out.loc[out['cnri'] > threshold, 'sentiment_signal'] = 1.0
    out.loc[out['cnri'] < -threshold, 'sentiment_signal'] = -1.0
    strength = (out['cnri'].abs() / max(threshold, 1e-6)).clip(lower=0.0, upper=1.0)
    out['target_exposure'] = out['sentiment_signal'] * strength
    out = out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'returns', 'return_z', 'volume_z', 'daily_sentiment_proxy', 'cnri', 'sentiment_signal', 'target_exposure',
    ]].copy()
    return out.dropna()


class Mt5SentimentFeed(bt.feeds.PandasData):
    lines = ('returns', 'return_z', 'volume_z', 'daily_sentiment_proxy', 'cnri', 'sentiment_signal', 'target_exposure',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('returns', 6), ('return_z', 7), ('volume_z', 8), ('daily_sentiment_proxy', 9), ('cnri', 10),
        ('sentiment_signal', 11), ('target_exposure', 12),
    )


class SentimentSignalStrategy(bt.Strategy):
    params = dict(
        sentiment_window=30,
        threshold=0.15,
        holding_period=21,
        max_exposure=1.0,
        return_z_window=20,
        volume_window=30,
        volume_impact_weight=0.5,
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
        self.rebalance_count = 0
        self.last_rebalance_bar = 0
        self.cnri_history = []
        self.bullish_signal_days = 0
        self.bearish_signal_days = 0
        self.neutral_signal_days = 0

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        direction = 1.0 if target_notional_pct >= 0 else -1.0
        size = broker_value * abs(float(target_notional_pct)) / (execution_price * multiplier)
        return direction * round(size, 2)

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        current_signal = float(self.data.sentiment_signal[0])
        current_cnri = float(self.data.cnri[0])
        self.cnri_history.append(current_cnri)
        if current_signal > 0:
            self.bullish_signal_days += 1
        elif current_signal < 0:
            self.bearish_signal_days += 1
        else:
            self.neutral_signal_days += 1
        if self.pending_order is not None:
            return
        if self.last_rebalance_bar and (self.bar_num - self.last_rebalance_bar) < int(self.p.holding_period):
            return
        target_exposure = max(-float(self.p.max_exposure), min(float(self.p.max_exposure), float(self.data.target_exposure[0]) * float(self.p.max_exposure)))
        target_size = self._get_position_size(target_notional_pct=target_exposure)
        current_size = float(self.position.size)
        if abs(target_size - current_size) < 0.01:
            return
        if target_size > current_size:
            self.buy_count += 1
        elif target_size < current_size:
            self.sell_count += 1
        self.rebalance_count += 1
        self.last_rebalance_bar = self.bar_num
        self.pending_order = self.order_target_size(target=target_size)

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
