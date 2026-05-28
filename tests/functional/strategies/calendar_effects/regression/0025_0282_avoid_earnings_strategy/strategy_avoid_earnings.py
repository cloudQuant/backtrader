from __future__ import absolute_import, division, print_function, unicode_literals

import io
from datetime import datetime

import backtrader as bt
import numpy as np
import pandas as pd

FOMC_MONTHS = (1, 3, 5, 6, 7, 9, 11, 12)


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


def generate_fomc_proxy_dates(start_year, end_year):
    dates = []
    for year in range(start_year, end_year + 1):
        for month in FOMC_MONTHS:
            wednesdays = pd.date_range(start=f'{year}-{month:02d}-01', end=f'{year}-{month:02d}-28', freq='W-WED')
            if len(wednesdays) >= 3:
                dates.append(wednesdays[2].to_pydatetime())
            elif len(wednesdays) > 0:
                dates.append(wednesdays[-1].to_pydatetime())
    return dates


def generate_nfp_proxy_dates(start_year, end_year):
    dates = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            fridays = pd.date_range(start=f'{year}-{month:02d}-01', end=f'{year}-{month:02d}-07', freq='W-FRI')
            if len(fridays) > 0:
                dates.append(fridays[0].to_pydatetime())
    return dates


def generate_cpi_proxy_dates(start_year, end_year):
    return [datetime(year, month, min(10, 28)) for year in range(start_year, end_year + 1) for month in range(1, 13)]


def align_event_dates(index, event_dates):
    aligned = []
    for event_date in event_dates:
        ts = pd.Timestamp(event_date)
        loc = index.searchsorted(ts)
        if loc >= len(index):
            continue
        aligned_ts = index[loc]
        if abs((aligned_ts - ts).days) <= 3:
            aligned.append(aligned_ts)
    return sorted(set(aligned))


def mark_avoid_windows(index, event_dates, before_days, after_days):
    series = pd.Series(0.0, index=index)
    index_map = {ts: i for i, ts in enumerate(index)}
    for event_date in event_dates:
        if event_date not in index_map:
            continue
        loc = index_map[event_date]
        start = max(0, loc - before_days)
        end = min(len(index) - 1, loc + after_days)
        series.iloc[start:end + 1] = 1.0
    return series


def prepare_avoid_earnings_features(df, params):
    out = df.copy()
    fast_ma_period = int(params.get('fast_ma_period', 20))
    slow_ma_period = int(params.get('slow_ma_period', 100))
    volatility_lookback = int(params.get('volatility_lookback', 20))
    volatility_threshold = float(params.get('volatility_threshold', 1.5))

    out['fast_ma'] = out['close'].rolling(fast_ma_period).mean()
    out['slow_ma'] = out['close'].rolling(slow_ma_period).mean()
    out['base_signal'] = (out['fast_ma'] > out['slow_ma']).astype(float)
    returns = out['close'].pct_change()
    out['current_vol'] = returns.rolling(volatility_lookback).std() * np.sqrt(252)
    out['historical_vol'] = out['current_vol'].rolling(252, min_periods=60).mean()
    out['high_volatility'] = (out['current_vol'] > out['historical_vol'] * volatility_threshold).astype(float)

    index = out.index
    start_year = index[0].year
    end_year = index[-1].year
    nfp_dates = align_event_dates(index, generate_nfp_proxy_dates(start_year, end_year))
    cpi_dates = align_event_dates(index, generate_cpi_proxy_dates(start_year, end_year))
    fomc_dates = align_event_dates(index, generate_fomc_proxy_dates(start_year, end_year))

    out['near_data_event'] = 0.0
    out['near_fomc_event'] = 0.0
    out['near_data_event'] = mark_avoid_windows(
        index,
        sorted(set(nfp_dates + cpi_dates)),
        int(params.get('avoid_days_before_data', 2)),
        int(params.get('avoid_days_after_data', 1)),
    )
    out['near_fomc_event'] = mark_avoid_windows(
        index,
        fomc_dates,
        int(params.get('avoid_days_before_fomc', 3)),
        int(params.get('avoid_days_after_fomc', 1)),
    )
    out['avoid_event'] = ((out['near_data_event'] > 0.5) | (out['near_fomc_event'] > 0.5)).astype(float)

    out['target_position'] = np.where(
        out['base_signal'] > 0.5,
        np.where(out['avoid_event'] > 0.5, 0.0, np.where(out['high_volatility'] > 0.5, 0.30, 0.95)),
        0.0,
    )
    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'fast_ma', 'slow_ma', 'base_signal', 'current_vol', 'historical_vol', 'high_volatility',
        'near_data_event', 'near_fomc_event', 'avoid_event', 'target_position',
    ]
    return out[cols].dropna()


class AvoidEarningsFeed(bt.feeds.PandasData):
    lines = (
        'fast_ma', 'slow_ma', 'base_signal', 'current_vol', 'historical_vol', 'high_volatility',
        'near_data_event', 'near_fomc_event', 'avoid_event', 'target_position',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('fast_ma', 6), ('slow_ma', 7), ('base_signal', 8), ('current_vol', 9), ('historical_vol', 10), ('high_volatility', 11),
        ('near_data_event', 12), ('near_fomc_event', 13), ('avoid_event', 14), ('target_position', 15),
    )


class AvoidEarningsStrategy(bt.Strategy):
    params = dict(
        position_size=0.95,
        reduced_position=0.30,
        fast_ma_period=20,
        slow_ma_period=100,
        avoid_days_before_data=2,
        avoid_days_after_data=1,
        avoid_days_before_fomc=3,
        avoid_days_after_fomc=1,
        volatility_lookback=20,
        volatility_threshold=1.5,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.avoid_days = 0
        self.reduced_days = 0
        self.pending_order = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return

        target = float(self.data.target_position[0])
        if float(self.data.avoid_event[0]) > 0.5:
            self.avoid_days += 1
        elif float(self.data.high_volatility[0]) > 0.5 and target > 0:
            self.reduced_days += 1

        current_size = float(self.position.size)
        current_target_pct = 0.0
        if current_size != 0 and float(self.data.close[0]) > 0 and float(self.broker.getvalue()) > 0:
            current_target_pct = current_size * float(self.data.close[0]) / float(self.broker.getvalue())
        if abs(target - current_target_pct) < 0.02:
            return
        if target > current_target_pct:
            self.buy_count += 1
        elif target < current_target_pct:
            self.sell_count += 1
        self.pending_order = self.order_target_percent(target=target)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
