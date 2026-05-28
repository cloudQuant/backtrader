from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
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
    df = df.rename(columns={'<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close', '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume'})
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_trend_equity_features(df, params):
    out = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    lookbacks = [int(x) for x in params.get('lookback_periods', [63, 126, 252])]
    weights = list(params.get('weights', [0.2, 0.3, 0.5]))
    vol_lookback = int(params.get('volatility_lookback', 21))
    out['returns'] = out['close'].pct_change()
    for lb in lookbacks:
        out[f'ret_{lb}'] = out['close'].pct_change(lb)
        out[f'score_{lb}'] = (out[f'ret_{lb}'] > 0).astype(float)
    out['trend_score'] = 0.0
    for lb, w in zip(lookbacks, weights):
        out['trend_score'] += out[f'score_{lb}'] * float(w)
    out['volatility'] = out['returns'].rolling(vol_lookback).std() * math.sqrt(252.0)
    cumulative = (1.0 + out['returns'].fillna(0.0)).cumprod()
    running_max = cumulative.cummax()
    out['drawdown'] = cumulative / running_max - 1.0
    cols = ['open', 'high', 'low', 'close', 'volume', 'openinterest', 'returns', 'trend_score', 'volatility', 'drawdown']
    return out[cols].dropna().copy()


class TrendEquityFeed(bt.feeds.PandasData):
    lines = ('returns', 'trend_score', 'volatility', 'drawdown',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('returns', 6), ('trend_score', 7), ('volatility', 8), ('drawdown', 9),
    )


class TrendEquityStrategy(bt.Strategy):
    params = dict(
        volatility_target=0.15,
        rebalance_interval_days=21,
        rebalance_threshold=0.05,
        max_drawdown=0.10,
        lookback_period_1=63,
        lookback_period_2=126,
        lookback_period_3=252,
        weight_1=0.2,
        weight_2=0.3,
        weight_3=0.5,
        volatility_lookback=21,
        commission_pct=0.0005,
        lot=0.1,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.rebalance_count = 0
        self.pending_order = None
        self.broker_value_series = []
        self.long_days = 0
        self.flat_days = 0

    def _current_weight(self):
        value = float(self.broker.getvalue())
        if value <= 0 or not self.position:
            return 0.0
        return float(self.position.size) * float(self.data.close[0]) / value

    def _target_weight(self):
        score = float(self.data.trend_score[0])
        vol = float(self.data.volatility[0]) if self.data.volatility[0] == self.data.volatility[0] else 0.0
        drawdown = float(self.data.drawdown[0]) if self.data.drawdown[0] == self.data.drawdown[0] else 0.0
        if vol <= 0:
            target = score
        else:
            target = min(1.0, score * min(float(self.p.volatility_target) / vol, 1.5))
        if drawdown < -float(self.p.max_drawdown):
            target *= 0.5
        return max(0.0, min(1.0, target))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        target = self._target_weight()
        if target > 0.5:
            self.long_days += 1
        else:
            self.flat_days += 1
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0 and abs(target - self._current_weight()) < float(self.p.rebalance_threshold):
            return
        current = self._current_weight()
        if abs(target - current) < float(self.p.rebalance_threshold):
            return
        if target > current:
            self.buy_count += 1
        else:
            self.sell_count += 1
        self.rebalance_count += 1
        self.pending_order = self.order_target_percent(target=target)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
