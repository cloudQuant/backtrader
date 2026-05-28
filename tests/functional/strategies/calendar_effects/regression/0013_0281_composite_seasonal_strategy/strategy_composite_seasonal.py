from __future__ import absolute_import, division, print_function, unicode_literals

import calendar
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


def get_week_of_month(ts):
    return (ts.day - 1) // 7 + 1


def prepare_composite_seasonal_features(df, params):
    out = df.copy()
    idx = out.index
    months = idx.month
    weekdays = idx.weekday
    day_numbers = idx.day
    month_period = idx.to_period('M')

    month_start_rank = pd.Series(range(len(out)), index=idx).groupby(month_period).transform(lambda x: x.rank(method='first'))
    month_end_rank = pd.Series(range(len(out)), index=idx).groupby(month_period).transform(lambda x: x.rank(ascending=False, method='first'))

    month_start_weight = float(params.get('month_start_weight', 0.8))
    month_end_weight = float(params.get('month_end_weight', 0.8))
    friday_weight = float(params.get('friday_weight', 0.3))
    monday_weight = float(params.get('monday_weight', 0.5))
    indian_wedding_weight = float(params.get('indian_wedding_weight', 1.5))
    chinese_new_year_weight = float(params.get('chinese_new_year_weight', 1.2))
    summer_slowdown_weight = float(params.get('summer_slowdown_weight', 0.8))
    entry_threshold = float(params.get('entry_threshold', 0.8))
    max_abs_score = float(params.get('max_abs_score', 3.0))
    base_position_size = float(params.get('base_position_size', 0.10))
    max_position_size = float(params.get('max_position_size', 0.15))
    allow_short = bool(params.get('allow_short', True))

    out['month_start_effect'] = (month_start_rank <= 3).astype(float) * month_start_weight
    out['month_end_effect'] = (month_end_rank <= 3).astype(float) * month_end_weight
    out['friday_effect'] = (weekdays == 4).astype(float) * friday_weight
    out['monday_effect'] = (weekdays == 0).astype(float) * (-monday_weight)
    out['indian_wedding_effect'] = pd.Index(months).isin([9, 10, 11, 12]).astype(float) * indian_wedding_weight
    out['chinese_new_year_effect'] = ((pd.Index(months) == 1) & (pd.Index([get_week_of_month(ts) for ts in idx]) <= 3)).astype(float) * chinese_new_year_weight
    out['summer_slowdown_effect'] = pd.Index(months).isin([6, 7, 8]).astype(float) * (-summer_slowdown_weight)

    out['seasonal_score'] = (
        out['month_start_effect'] + out['month_end_effect'] + out['friday_effect'] +
        out['monday_effect'] + out['indian_wedding_effect'] + out['chinese_new_year_effect'] +
        out['summer_slowdown_effect']
    )
    clipped_score = out['seasonal_score'].clip(lower=-max_abs_score, upper=max_abs_score)
    strength = (clipped_score.abs() / max_abs_score).clip(lower=0.0, upper=1.0)
    out['signal_direction'] = np.where(out['seasonal_score'] > entry_threshold, 1.0, np.where(out['seasonal_score'] < -entry_threshold, -1.0 if allow_short else 0.0, 0.0))
    out['target_position'] = np.where(
        out['signal_direction'] == 0.0,
        0.0,
        np.sign(out['signal_direction']) * (base_position_size + (max_position_size - base_position_size) * strength)
    )
    out['strong_signal'] = (out['seasonal_score'].abs() >= 2.0).astype(float)
    out['weak_signal'] = ((out['seasonal_score'].abs() >= entry_threshold) & (out['seasonal_score'].abs() < 2.0)).astype(float)
    out['neutral_signal'] = (out['signal_direction'] == 0.0).astype(float)

    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'month_start_effect', 'month_end_effect', 'friday_effect', 'monday_effect',
        'indian_wedding_effect', 'chinese_new_year_effect', 'summer_slowdown_effect',
        'seasonal_score', 'signal_direction', 'target_position', 'strong_signal', 'weak_signal', 'neutral_signal',
    ]
    return out[cols].dropna()


class CompositeSeasonalFeed(bt.feeds.PandasData):
    lines = (
        'month_start_effect', 'month_end_effect', 'friday_effect', 'monday_effect',
        'indian_wedding_effect', 'chinese_new_year_effect', 'summer_slowdown_effect',
        'seasonal_score', 'signal_direction', 'target_position', 'strong_signal', 'weak_signal', 'neutral_signal',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month_start_effect', 6), ('month_end_effect', 7), ('friday_effect', 8), ('monday_effect', 9),
        ('indian_wedding_effect', 10), ('chinese_new_year_effect', 11), ('summer_slowdown_effect', 12),
        ('seasonal_score', 13), ('signal_direction', 14), ('target_position', 15), ('strong_signal', 16), ('weak_signal', 17), ('neutral_signal', 18),
    )


class CompositeSeasonalStrategy(bt.Strategy):
    params = dict(
        month_start_weight=0.8,
        month_end_weight=0.8,
        friday_weight=0.3,
        monday_weight=0.5,
        indian_wedding_weight=1.5,
        chinese_new_year_weight=1.2,
        summer_slowdown_weight=0.8,
        entry_threshold=0.8,
        max_abs_score=3.0,
        base_position_size=0.1,
        max_position_size=0.15,
        allow_short=True,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.strong_days = 0
        self.weak_days = 0
        self.neutral_days = 0
        self.pending_order = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return

        if float(self.data.strong_signal[0]) > 0.5:
            self.strong_days += 1
        elif float(self.data.weak_signal[0]) > 0.5:
            self.weak_days += 1
        else:
            self.neutral_days += 1

        target = float(self.data.target_position[0])
        position_value_pct = 0.0
        if self.position.size and float(self.data.close[0]) > 0 and float(self.broker.getvalue()) > 0:
            position_value_pct = self.position.size * float(self.data.close[0]) / float(self.broker.getvalue())
        if abs(target - position_value_pct) < 0.02:
            return
        if target > position_value_pct:
            self.buy_count += 1
        elif target < position_value_pct:
            self.sell_count += 1
        self.pending_order = self.order_target_percent(target=target)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
