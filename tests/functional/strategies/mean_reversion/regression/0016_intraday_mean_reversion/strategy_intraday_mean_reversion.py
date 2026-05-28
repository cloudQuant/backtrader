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
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
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


def prepare_intraday_mean_reversion_features(df, params):
    entry_z = float(params.get('entry_z', 2.0))
    exit_z = float(params.get('exit_z', 0.5))
    lookback_days = int(params.get('lookback_days', 252))
    max_holding_hours = float(params.get('max_holding_hours', 4))
    early_entry_cutoff = int(params.get('early_entry_cutoff', 14))
    gross_exposure = float(params.get('gross_exposure', 0.95))

    frame = df.copy()
    frame['session_date'] = frame.index.date
    frame['bar_slot'] = frame.groupby('session_date').cumcount()
    frame['session_open'] = frame.groupby('session_date')['open'].transform('first')
    frame['intraday_return'] = frame['close'] / frame['session_open'] - 1.0

    grouped = frame.groupby('bar_slot')['intraday_return']
    frame['slot_mean'] = grouped.transform(lambda s: s.shift(1).rolling(lookback_days, min_periods=max(20, lookback_days // 4)).mean())
    frame['slot_std'] = grouped.transform(lambda s: s.shift(1).rolling(lookback_days, min_periods=max(20, lookback_days // 4)).std())
    frame['zscore'] = (frame['intraday_return'] - frame['slot_mean']) / frame['slot_std']
    frame['is_eod'] = frame['session_date'] != frame['session_date'].shift(-1)

    bars_per_hour = 4
    max_holding_bars = max(1, int(max_holding_hours * bars_per_hour))

    target_pct = []
    signal_change = []
    position = 0.0
    hold_bars = 0
    prev_target = 0.0

    for row in frame.itertuples():
        z = row.zscore
        hour = row.Index.hour
        if position == 0.0:
            hold_bars = 0
            if pd.notna(z) and hour < early_entry_cutoff:
                if z <= -entry_z:
                    position = gross_exposure
                    hold_bars = 1
                elif z >= entry_z:
                    position = -gross_exposure
                    hold_bars = 1
        else:
            hold_bars += 1
            should_exit = False
            if pd.notna(z) and abs(z) <= exit_z:
                should_exit = True
            if hold_bars >= max_holding_bars:
                should_exit = True
            if bool(row.is_eod):
                should_exit = True
            if should_exit:
                position = 0.0
                hold_bars = 0

        target_pct.append(position)
        signal_change.append(1.0 if position != prev_target else 0.0)
        prev_target = position

    frame['target_pct'] = target_pct
    frame['signal_change'] = signal_change
    feature_cols = ['open', 'high', 'low', 'close', 'volume', 'openinterest', 'zscore', 'target_pct', 'signal_change']
    return frame[feature_cols].dropna()


class MeanReversionSignalFeed(bt.feeds.PandasData):
    lines = ('zscore', 'target_pct', 'signal_change')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('zscore', 6), ('target_pct', 7), ('signal_change', 8),
    )


class GoldIntradayMeanReversionStrategy(bt.Strategy):
    params = dict(
        entry_z=2.0,
        exit_z=0.5,
        lookback_days=252,
        max_holding_hours=4,
        early_entry_cutoff=14,
        gross_exposure=0.95,
    )

    def __init__(self):
        self.bar_num = 0
        self.pending_order = None
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.signal_change_count = 0
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if float(self.data.signal_change[0]) <= 0.5:
            return
        self.signal_change_count += 1
        self.pending_order = self.order_target_percent(target=float(self.data.target_pct[0]))

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
