from __future__ import absolute_import, division, print_function, unicode_literals

import io

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


def prepare_gold_quantpedia_features(df, params):
    trend_lookback_months = int(params.get('trend_lookback_months', 12))
    skew_lookback_months = int(params.get('skew_lookback_months', 24))
    payday_window_days = int(params.get('payday_window_days', 5))
    trend_weight = float(params.get('trend_weight', 0.5))
    skew_weight = float(params.get('skew_weight', 0.3))
    payday_weight = float(params.get('payday_weight', 0.2))
    entry_threshold = float(params.get('entry_threshold', 0.35))

    out = df.copy()
    monthly_close = out['close'].resample('ME').last()
    monthly_returns = monthly_close.pct_change()
    trend_signal = (monthly_close.pct_change(trend_lookback_months) > 0).astype(float)
    skew_signal = (monthly_returns.rolling(skew_lookback_months).skew() < 0).astype(float)

    out['trend_signal'] = trend_signal.reindex(out.index, method='ffill').fillna(0.0)
    out['skew_signal'] = skew_signal.reindex(out.index, method='ffill').fillna(0.0)
    out['payday_signal'] = (out.index.day <= payday_window_days).astype(float)
    out['combined_score'] = (
        trend_weight * out['trend_signal'] +
        skew_weight * out['skew_signal'] +
        payday_weight * out['payday_signal']
    )
    out['target_pct'] = out['combined_score'].where(out['combined_score'] >= entry_threshold, 0.0).clip(lower=0.0, upper=1.0)
    out['entry_signal'] = ((out['target_pct'] > 0) & (out['target_pct'].shift(1).fillna(0.0) <= 0)).astype(float)
    out['exit_signal'] = ((out['target_pct'] <= 0) & (out['target_pct'].shift(1).fillna(0.0) > 0)).astype(float)

    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'trend_signal', 'skew_signal', 'payday_signal', 'combined_score',
        'target_pct', 'entry_signal', 'exit_signal'
    ]
    return out[cols].dropna(subset=['open', 'high', 'low', 'close'])


class GoldQuantpediaFeed(bt.feeds.PandasData):
    lines = ('trend_signal', 'skew_signal', 'payday_signal', 'combined_score', 'target_pct', 'entry_signal', 'exit_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('trend_signal', 6), ('skew_signal', 7), ('payday_signal', 8), ('combined_score', 9), ('target_pct', 10), ('entry_signal', 11), ('exit_signal', 12),
    )


class GoldQuantpediaStrategy(bt.Strategy):
    params = dict(
        trend_lookback_months=12,
        skew_lookback_months=24,
        payday_window_days=5,
        trend_weight=0.5,
        skew_weight=0.3,
        payday_weight=0.2,
        entry_threshold=0.35,
        commission_pct=0.0002,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.last_target = 0.0
        self.broker_value_series = []

    def _get_target_size(self, target_notional_pct, price=None):
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
        return max(0.0, round(size, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        target_pct = float(self.data.target_pct[0]) if self.data.target_pct[0] == self.data.target_pct[0] else 0.0
        target_size = self._get_target_size(target_pct)
        current_size = float(self.position.size)
        if abs(target_pct - self.last_target) < 1e-8 and abs(target_size - current_size) < 0.01:
            return
        if target_pct > 0 and self.last_target <= 0:
            self.buy_count += 1
        elif target_pct <= 0 and self.last_target > 0:
            self.sell_count += 1
        self.pending_order = self.order_target_size(target=target_size)
        self.last_target = target_pct

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
