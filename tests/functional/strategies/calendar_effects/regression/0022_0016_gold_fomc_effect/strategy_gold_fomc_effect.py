from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
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


def prepare_gold_fomc_effect_features(df, params):
    out = df.copy()
    pre_event_days = int(params.get('pre_event_days', 5))
    trend_lookback = int(params.get('trend_lookback', 20))
    vol_lookback = int(params.get('vol_lookback', 20))
    hold_days_after_event = int(params.get('hold_days_after_event', 1))
    min_history_events = int(params.get('min_history_events', 4))
    stop_vol_multiplier = float(params.get('stop_vol_multiplier', 2.0))
    min_stop_pct = float(params.get('min_stop_pct', 0.01))
    max_stop_pct = float(params.get('max_stop_pct', 0.05))
    allow_short = bool(params.get('allow_short', False))

    out['daily_return'] = out['close'].pct_change()
    out['rolling_vol'] = out['daily_return'].rolling(vol_lookback).std()
    out['entry_signal'] = 0.0
    out['exit_signal'] = 0.0
    out['event_id'] = -1.0
    out['direction'] = 0.0
    out['expected_drift'] = np.nan
    out['current_trend'] = np.nan
    out['stop_pct'] = np.nan
    out['is_event_day'] = 0.0

    index = out.index
    event_dates = align_event_dates(index, generate_fomc_proxy_dates(index[0].year, index[-1].year))
    historical_pre_returns = []

    for event_id, event_date in enumerate(event_dates):
        event_loc = index.get_loc(event_date)
        if event_loc < max(pre_event_days, trend_lookback):
            continue
        out.iloc[event_loc, out.columns.get_loc('is_event_day')] = 1.0
        entry_loc = event_loc - pre_event_days
        exit_loc = min(len(index) - 1, event_loc + hold_days_after_event)
        current_trend = out['close'].iloc[entry_loc] / out['close'].iloc[entry_loc - trend_lookback] - 1.0
        realized_pre_return = out['close'].iloc[event_loc - 1] / out['close'].iloc[entry_loc] - 1.0 if event_loc - 1 >= entry_loc else 0.0
        historical_drift = float(np.mean(historical_pre_returns)) if len(historical_pre_returns) >= min_history_events else np.nan
        stop_pct = out['rolling_vol'].iloc[entry_loc]
        if pd.isna(stop_pct):
            historical_pre_returns.append(realized_pre_return)
            continue
        stop_pct = float(np.clip(stop_vol_multiplier * stop_pct * math.sqrt(pre_event_days), min_stop_pct, max_stop_pct))
        direction = 0
        if not pd.isna(historical_drift):
            if historical_drift > 0 and current_trend > 0:
                direction = 1
            elif historical_drift < 0 and current_trend < 0 and allow_short:
                direction = -1
        if direction != 0:
            entry_idx = out.index[entry_loc]
            exit_idx = out.index[exit_loc]
            out.loc[entry_idx, 'entry_signal'] = 1.0
            out.loc[entry_idx, 'direction'] = float(direction)
            out.loc[entry_idx, 'event_id'] = float(event_id)
            out.loc[entry_idx, 'expected_drift'] = historical_drift
            out.loc[entry_idx, 'current_trend'] = current_trend
            out.loc[entry_idx, 'stop_pct'] = stop_pct
            out.loc[exit_idx, 'exit_signal'] = 1.0
            out.loc[exit_idx, 'event_id'] = float(event_id)
        historical_pre_returns.append(realized_pre_return)

    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'daily_return', 'rolling_vol', 'entry_signal', 'exit_signal',
        'event_id', 'direction', 'expected_drift', 'current_trend', 'stop_pct', 'is_event_day'
    ]
    return out[cols].dropna(subset=['open', 'high', 'low', 'close'])


class Mt5GoldFomcEffectFeed(bt.feeds.PandasData):
    lines = (
        'daily_return', 'rolling_vol', 'entry_signal', 'exit_signal',
        'event_id', 'direction', 'expected_drift', 'current_trend', 'stop_pct', 'is_event_day'
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('daily_return', 6), ('rolling_vol', 7), ('entry_signal', 8), ('exit_signal', 9),
        ('event_id', 10), ('direction', 11), ('expected_drift', 12), ('current_trend', 13), ('stop_pct', 14), ('is_event_day', 15),
    )


class GoldFomcEffectStrategy(bt.Strategy):
    params = dict(
        event_position_pct=0.03,
        pause_after_losses=3,
        pause_events_after_losses=1,
        pre_event_days=5,
        trend_lookback=20,
        vol_lookback=20,
        hold_days_after_event=1,
        min_history_events=4,
        stop_vol_multiplier=2.0,
        min_stop_pct=0.01,
        max_stop_pct=0.05,
        allow_short=False,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.entry_price = None
        self.entry_direction = 0
        self.entry_event_id = None
        self.stop_price = None
        self.consecutive_losses = 0
        self.paused_events_remaining = 0
        self.last_skipped_event_id = None
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

        entry_signal = float(self.data.entry_signal[0]) > 0.5
        exit_signal = float(self.data.exit_signal[0]) > 0.5
        direction = int(round(float(self.data.direction[0]))) if float(self.data.direction[0]) == float(self.data.direction[0]) else 0
        event_id = int(round(float(self.data.event_id[0]))) if float(self.data.event_id[0]) == float(self.data.event_id[0]) and float(self.data.event_id[0]) >= 0 else None
        stop_pct = float(self.data.stop_pct[0]) if float(self.data.stop_pct[0]) == float(self.data.stop_pct[0]) else None

        if not self.position:
            if not entry_signal or direction == 0 or event_id is None:
                return
            if self.paused_events_remaining > 0:
                if self.last_skipped_event_id != event_id:
                    self.paused_events_remaining -= 1
                    self.last_skipped_event_id = event_id
                return
            size = self._get_position_size(target_notional_pct=float(self.p.event_position_pct))
            if direction > 0:
                self.buy_count += 1
                self.pending_order = self.buy(size=size)
                self.stop_price = float(self.data.close[0]) * (1.0 - (stop_pct or 0.02))
            else:
                self.sell_count += 1
                self.pending_order = self.sell(size=size)
                self.stop_price = float(self.data.close[0]) * (1.0 + (stop_pct or 0.02))
            self.entry_price = float(self.data.close[0])
            self.entry_direction = direction
            self.entry_event_id = event_id
            return

        if self.entry_direction > 0 and self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
            self.sell_count += 1
            self.pending_order = self.close()
            return
        if self.entry_direction < 0 and self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
            self.buy_count += 1
            self.pending_order = self.close()
            return
        if exit_signal and event_id == self.entry_event_id:
            if self.entry_direction > 0:
                self.sell_count += 1
            else:
                self.buy_count += 1
            self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.entry_price = None
        self.entry_direction = 0
        self.entry_event_id = None
        self.stop_price = None
        if trade.pnlcomm >= 0:
            self.win_count += 1
            self.consecutive_losses = 0
        else:
            self.loss_count += 1
            self.consecutive_losses += 1
            if self.consecutive_losses >= int(self.p.pause_after_losses):
                self.paused_events_remaining = int(self.p.pause_events_after_losses)
                self.consecutive_losses = 0
                self.last_skipped_event_id = None
