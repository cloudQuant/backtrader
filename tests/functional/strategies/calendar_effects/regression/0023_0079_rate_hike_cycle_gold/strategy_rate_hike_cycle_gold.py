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
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_rate_hike_inputs(asset_frames, params):
    common_index = None
    for frame in asset_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    aligned = {name: frame.loc[common_index].copy() for name, frame in asset_frames.items()}
    signal_df = aligned['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    ratio = np.log(aligned['IEF']['close'] / aligned['GTIP']['close']).replace([np.inf, -np.inf], np.nan)
    window = int(params.get('proxy_window', 60))
    proxy_mean = ratio.rolling(window, min_periods=window).mean()
    proxy_std = ratio.rolling(window, min_periods=window).std().replace(0, np.nan)
    signal_df['real_rate_proxy'] = ratio
    signal_df['real_rate_zscore'] = ((ratio - proxy_mean) / proxy_std).replace([np.inf, -np.inf], np.nan)
    signal_df['real_rate_slope'] = signal_df['real_rate_proxy'].diff(5)
    signal_df['target_signal'] = 0.0
    signal_df['cycle_phase'] = 0.0
    signal_df['cycle_id'] = 0.0
    signal_df['hike_start_flag'] = 0.0

    hike_start_dates = [pd.Timestamp(x) for x in params.get('hike_start_dates', [])]
    threshold = float(params.get('real_rate_threshold', 0.5))
    position_size = float(params.get('position_size', 0.5))
    short_term_days = int(params.get('short_term_days', 30))
    long_term_days = int(params.get('long_term_days', 252))

    valid_index = signal_df.index
    cycle_num = 0
    for raw_date in hike_start_dates:
        later_dates = valid_index[valid_index >= raw_date]
        if len(later_dates) == 0:
            continue
        cycle_num += 1
        hike_date = later_dates[0]
        signal_df.loc[hike_date, 'hike_start_flag'] = 1.0
        signal_df.loc[hike_date, 'cycle_id'] = float(cycle_num)
        short_end = hike_date + pd.Timedelta(days=short_term_days)
        long_end = hike_date + pd.Timedelta(days=long_term_days)
        short_mask = (valid_index >= hike_date) & (valid_index <= short_end)
        signal_df.loc[short_mask, 'target_signal'] = -position_size
        signal_df.loc[short_mask, 'cycle_phase'] = 1.0
        signal_df.loc[short_mask, 'cycle_id'] = float(cycle_num)
        long_mask = (valid_index > short_end) & (valid_index <= long_end)
        long_dates = valid_index[long_mask]
        for dt in long_dates:
            zscore = signal_df.at[dt, 'real_rate_zscore']
            slope = signal_df.at[dt, 'real_rate_slope']
            if pd.isna(zscore) or pd.isna(slope):
                continue
            if zscore <= -threshold and slope < 0:
                signal_df.at[dt, 'target_signal'] = position_size
            elif zscore >= threshold and slope > 0:
                signal_df.at[dt, 'target_signal'] = -position_size
            else:
                signal_df.at[dt, 'target_signal'] = 0.0
            signal_df.at[dt, 'cycle_phase'] = 2.0
            signal_df.at[dt, 'cycle_id'] = float(cycle_num)

    signal_df = signal_df.dropna(subset=['real_rate_zscore']).copy()
    aligned = {name: frame.loc[signal_df.index].copy() for name, frame in aligned.items()}
    return aligned, signal_df


class RateHikeSignalFeed(bt.feeds.PandasData):
    lines = ('real_rate_proxy', 'real_rate_zscore', 'real_rate_slope', 'target_signal', 'cycle_phase', 'cycle_id', 'hike_start_flag')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('real_rate_proxy', 6), ('real_rate_zscore', 7), ('real_rate_slope', 8), ('target_signal', 9), ('cycle_phase', 10), ('cycle_id', 11), ('hike_start_flag', 12),
    )


class RateHikeCycleGoldStrategy(bt.Strategy):
    params = dict(
        position_size=0.5,
        hike_start_dates=['2015-12-16', '2022-03-16'],
        short_term_days=30,
        long_term_days=252,
        proxy_window=60,
        real_rate_threshold=0.5,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.gold = self.getdatabyname('XAUUSD')
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.switch_count = 0
        self.hike_event_count = 0
        self.last_target_signal = 0.0
        self.broker_value_series = []

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _target_size(self, target_signal):
        broker_value = float(self.broker.getvalue())
        price = float(self.gold.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.gold)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        raw_size = broker_value * float(target_signal) / (price * multiplier)
        return round(raw_size, 2)

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        if float(self.signal.hike_start_flag[0]) > 0.5:
            self.hike_event_count += 1
        target_signal = float(self.signal.target_signal[0])
        if abs(target_signal - self.last_target_signal) < 1e-9:
            return
        current_size = float(self.getposition(self.gold).size)
        target_size = self._target_size(target_signal)
        order = self.order_target_size(data=self.gold, target=target_size)
        self._submit(order)
        if order is not None:
            if target_size > current_size:
                self.buy_count += 1
            elif target_size < current_size:
                self.sell_count += 1
            if self.last_target_signal != 0.0 and target_signal != self.last_target_signal:
                self.switch_count += 1
        self.last_target_signal = target_signal

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)
