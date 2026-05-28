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


def resample_to_monthly(df):
    monthly = pd.DataFrame({
        'open': df['open'].resample('ME').first(),
        'high': df['high'].resample('ME').max(),
        'low': df['low'].resample('ME').min(),
        'close': df['close'].resample('ME').last(),
        'volume': df['volume'].resample('ME').sum(),
        'openinterest': df['openinterest'].resample('ME').last().fillna(0),
    })
    return monthly.dropna(subset=['open', 'high', 'low', 'close'])


def prepare_momentum_basic_data(daily_df, params):
    monthly = resample_to_monthly(daily_df)
    momentum_period = int(params.get('momentum_period_months', 12))
    short_momentum_period = int(params.get('short_momentum_period_months', 3))
    premium_lookback = int(params.get('premium_lookback_months', 24))
    prediction_weight_adj = float(params.get('prediction_weight_adj', 0.10))
    base_weight = float(params.get('base_weight', 0.80))
    max_weight = float(params.get('max_weight', 1.00))
    min_weight = float(params.get('min_weight', 0.30))
    volatility_target = float(params.get('volatility_target', 0.18))
    vol_lookback = int(params.get('vol_lookback_months', 6))
    allow_short = bool(params.get('allow_short', True))

    out = monthly.copy()
    out['returns_1m'] = out['close'].pct_change()
    out['momentum_long'] = out['close'].pct_change(momentum_period)
    out['momentum_short'] = out['close'].pct_change(short_momentum_period)
    out['realized_vol'] = out['returns_1m'].rolling(vol_lookback).std() * np.sqrt(12.0)
    out['future_return_proxy'] = out['returns_1m'].shift(-1)
    out['historical_premium'] = out['future_return_proxy'].rolling(premium_lookback).mean()

    premium_adjustment = np.where(
        out['historical_premium'] > out['historical_premium'].rolling(premium_lookback, min_periods=6).mean(),
        prediction_weight_adj,
        -prediction_weight_adj,
    )
    out['premium_adjustment'] = pd.Series(premium_adjustment, index=out.index).fillna(0.0)

    direction = np.where(out['momentum_long'] > 0, 1.0, np.where(out['momentum_long'] < 0, -1.0 if allow_short else 0.0, 0.0))
    vol_scale = np.where(out['realized_vol'] > 0, np.minimum(1.5, volatility_target / out['realized_vol']), 1.0)
    target_weight = (base_weight + out['premium_adjustment']).clip(lower=min_weight, upper=max_weight)
    out['target_weight'] = pd.Series(direction * target_weight * vol_scale, index=out.index).clip(lower=-max_weight if allow_short else 0.0, upper=max_weight)
    out['target_weight'] = out['target_weight'].fillna(0.0)
    out['signal_direction'] = pd.Series(direction, index=out.index).fillna(0.0)
    out['gross_exposure'] = out['target_weight'].abs()
    return out.dropna(subset=['momentum_long', 'momentum_short', 'realized_vol'])


class MomentumBasicFeed(bt.feeds.PandasData):
    lines = ('returns_1m', 'momentum_long', 'momentum_short', 'realized_vol', 'historical_premium', 'premium_adjustment', 'signal_direction', 'target_weight', 'gross_exposure',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('returns_1m', 6), ('momentum_long', 7), ('momentum_short', 8), ('realized_vol', 9), ('historical_premium', 10),
        ('premium_adjustment', 11), ('signal_direction', 12), ('target_weight', 13), ('gross_exposure', 14),
    )


class MomentumBasicStrategy(bt.Strategy):
    params = dict(
        rebalance_tolerance=0.02,
        momentum_period_months=12,
        short_momentum_period_months=3,
        premium_lookback_months=24,
        prediction_weight_adj=0.1,
        base_weight=0.8,
        max_weight=1.0,
        min_weight=0.3,
        volatility_target=0.18,
        vol_lookback_months=6,
        allow_short=True,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.rebalance_count = 0
        self.switch_count = 0
        self.long_months = 0
        self.short_months = 0
        self.cash_months = 0
        self.buy_count = 0
        self.sell_count = 0
        self.short_count = 0
        self.cover_count = 0
        self.pending_order = None
        self.last_target = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return

        target = float(self.data.target_weight[0])
        if target > 0:
            self.long_months += 1
        elif target < 0:
            self.short_months += 1
        else:
            self.cash_months += 1

        if self.last_target is not None and abs(target - self.last_target) < float(self.p.rebalance_tolerance):
            return
        if self.last_target is not None:
            self.switch_count += 1
        self.last_target = target
        self.rebalance_count += 1

        current_position = float(self.position.size)
        if target > 0 and current_position <= 0:
            self.buy_count += 1
        elif target < 0 and current_position >= 0:
            self.short_count += 1
        elif target == 0 and current_position > 0:
            self.sell_count += 1
        elif target == 0 and current_position < 0:
            self.cover_count += 1
        elif current_position > 0 and target < current_position:
            self.sell_count += 1
        elif current_position < 0 and target > current_position:
            self.cover_count += 1
        self.pending_order = self.order_target_percent(target=target)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
