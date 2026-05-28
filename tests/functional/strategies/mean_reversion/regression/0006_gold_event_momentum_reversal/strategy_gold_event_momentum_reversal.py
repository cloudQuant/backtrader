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
    dates = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            dates.append(datetime(year, month, min(10, 28)))
    return dates


def generate_month_turn_dates(index):
    idx = pd.Index(index)
    periods = idx.to_series(index=idx).dt.to_period('M')
    month_start = idx[periods != periods.shift(1)]
    month_end = idx[periods != periods.shift(-1)]
    return list(month_start.to_pydatetime()) + list(month_end.to_pydatetime())


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


def prepare_gold_event_momentum_reversal_features(df, params):
    out = df.copy()
    lookback = int(params.get('lookback', 20))
    momentum_threshold = float(params.get('momentum_threshold', 0.02))
    hold_days_after_event = int(params.get('hold_days_after_event', 3))
    ma_period = int(params.get('ma_period', 20))
    stop_loss_pct = float(params.get('stop_loss_pct', 0.015))
    take_profit_pct = float(params.get('take_profit_pct', 0.02))

    out['ma'] = out['close'].rolling(ma_period).mean()
    out['entry_signal'] = 0.0
    out['exit_signal'] = 0.0
    out['direction'] = 0.0
    out['event_id'] = -1.0
    out['pre_event_return'] = np.nan
    out['trend_state'] = np.nan
    out['stop_pct'] = np.nan
    out['take_profit_pct'] = np.nan
    out['is_event_day'] = 0.0

    index = out.index
    event_dates = []
    event_dates += generate_fomc_proxy_dates(index[0].year, index[-1].year)
    event_dates += generate_nfp_proxy_dates(index[0].year, index[-1].year)
    event_dates += generate_cpi_proxy_dates(index[0].year, index[-1].year)
    event_dates += generate_month_turn_dates(index)
    event_dates = align_event_dates(index, event_dates)

    for event_id, event_date in enumerate(event_dates):
        event_loc = index.get_loc(event_date)
        if event_loc < max(lookback, ma_period):
            continue
        out.iloc[event_loc, out.columns.get_loc('is_event_day')] = 1.0
        pre_event_return = out['close'].iloc[event_loc - 1] / out['close'].iloc[event_loc - lookback] - 1.0
        if abs(pre_event_return) < momentum_threshold:
            continue
        trend_up = float(out['close'].iloc[event_loc - 1]) > float(out['ma'].iloc[event_loc - 1])
        base_direction = -1 if pre_event_return > 0 else 1
        direction = base_direction if trend_up else -base_direction
        exit_loc = min(len(index) - 1, event_loc + hold_days_after_event)
        out.iloc[event_loc, out.columns.get_loc('entry_signal')] = 1.0
        out.iloc[event_loc, out.columns.get_loc('direction')] = float(direction)
        out.iloc[event_loc, out.columns.get_loc('event_id')] = float(event_id)
        out.iloc[event_loc, out.columns.get_loc('pre_event_return')] = float(pre_event_return)
        out.iloc[event_loc, out.columns.get_loc('trend_state')] = 1.0 if trend_up else 0.0
        out.iloc[event_loc, out.columns.get_loc('stop_pct')] = stop_loss_pct
        out.iloc[event_loc, out.columns.get_loc('take_profit_pct')] = take_profit_pct
        out.iloc[exit_loc, out.columns.get_loc('exit_signal')] = 1.0
        out.iloc[exit_loc, out.columns.get_loc('event_id')] = float(event_id)

    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'entry_signal', 'exit_signal', 'direction', 'event_id',
        'pre_event_return', 'trend_state', 'stop_pct', 'take_profit_pct', 'is_event_day'
    ]
    return out[cols].dropna(subset=['open', 'high', 'low', 'close'])


class GoldEventMomentumReversalFeed(bt.feeds.PandasData):
    lines = ('entry_signal', 'exit_signal', 'direction', 'event_id', 'pre_event_return', 'trend_state', 'stop_pct', 'take_profit_pct', 'is_event_day')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('entry_signal', 6), ('exit_signal', 7), ('direction', 8), ('event_id', 9), ('pre_event_return', 10), ('trend_state', 11), ('stop_pct', 12), ('take_profit_pct', 13), ('is_event_day', 14),
    )


class GoldEventMomentumReversalStrategy(bt.Strategy):
    params = dict(
        position_pct=0.10,
        allow_short=True,
        lookback=20,
        momentum_threshold=0.02,
        hold_days_after_event=3,
        ma_period=20,
        stop_loss_pct=0.015,
        take_profit_pct=0.02,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_price = None
        self.entry_direction = 0
        self.stop_price = None
        self.take_profit_price = None
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=0.10):
        broker_value = float(self.broker.getvalue())
        price = float(self.data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        return max(0.01, round(broker_value * target_notional_pct / price, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        close = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position:
            if self.entry_direction > 0:
                if self.stop_price is not None and low <= self.stop_price:
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
                if self.take_profit_price is not None and high >= self.take_profit_price:
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
            elif self.entry_direction < 0:
                if self.stop_price is not None and high >= self.stop_price:
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
                if self.take_profit_price is not None and low <= self.take_profit_price:
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
            if float(self.data.exit_signal[0]) > 0.5:
                if self.entry_direction > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
                self.pending_order = self.close()
                return
            return
        if float(self.data.entry_signal[0]) <= 0.5:
            return
        direction = int(round(float(self.data.direction[0]))) if self.data.direction[0] == self.data.direction[0] else 0
        if direction == 0 or (direction < 0 and not bool(self.p.allow_short)):
            return
        size = self._get_position_size(float(self.p.position_pct))
        stop_pct = float(self.data.stop_pct[0]) if self.data.stop_pct[0] == self.data.stop_pct[0] else 0.015
        take_profit_pct = float(self.data.take_profit_pct[0]) if self.data.take_profit_pct[0] == self.data.take_profit_pct[0] else 0.02
        self.entry_price = close
        self.entry_direction = direction
        if direction > 0:
            self.buy_count += 1
            self.pending_order = self.buy(size=size)
            self.stop_price = close * (1.0 - stop_pct)
            self.take_profit_price = close * (1.0 + take_profit_pct)
        else:
            self.sell_count += 1
            self.pending_order = self.sell(size=size)
            self.stop_price = close * (1.0 + stop_pct)
            self.take_profit_price = close * (1.0 - take_profit_pct)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.entry_direction = 0
            self.stop_price = None
            self.take_profit_price = None
