from __future__ import absolute_import, division, print_function, unicode_literals

import io
import backtrader as bt
import pandas as pd
import numpy as np


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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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



def prepare_probability_cones_features(df, params):
    lookback = int(params.get('lookback', 60))
    num_std = float(params.get('num_std', 2.0))

    out = df.copy()
    ret = out['close'].pct_change()
    mu = ret.rolling(lookback).mean()
    sigma = ret.rolling(lookback).std()
    expected_price = out['close'].shift(1) * (1 + mu)
    out['upper_cone'] = expected_price + num_std * sigma * out['close'].shift(1)
    out['lower_cone'] = expected_price - num_std * sigma * out['close'].shift(1)
    out['signal'] = 0.0
    out.loc[out['close'] < out['lower_cone'], 'signal'] = 1.0
    out.loc[out['close'] > out['upper_cone'], 'signal'] = -1.0

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest',
               'upper_cone', 'lower_cone', 'signal']].copy()
    return out.dropna()


class Mt5ProbabilityConesFeed(bt.feeds.PandasData):
    lines = ('upper_cone', 'lower_cone', 'signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('upper_cone', 6),
        ('lower_cone', 7),
        ('signal', 8),
    )


class ProbabilityConesStrategy(bt.Strategy):
    params = dict(
        lookback=60,
        num_std=2.0,
        lot_size=1.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_bar = 0
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
        signal = float(self.data.signal[0])
        if not self.position:
            if signal > 0.5:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size())
        else:
            if signal < -0.5 or abs(signal) < 0.01:
                self.sell_count += 1
                self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        pass

