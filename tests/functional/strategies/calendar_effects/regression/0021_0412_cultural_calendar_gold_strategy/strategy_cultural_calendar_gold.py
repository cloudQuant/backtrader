from __future__ import absolute_import, division, print_function, unicode_literals

import io
from datetime import datetime

import backtrader as bt
import pandas as pd

HOLIDAY_DEFINITIONS = {
    'diwali': {'month': 11, 'day': 1, 'default_entry_days_before': 20, 'default_exit_days_after': 5, 'default_weight': 1.2, 'code': 1.0},
    'lunar_new_year': {'month': 2, 'day': 1, 'default_entry_days_before': 20, 'default_exit_days_after': 5, 'default_weight': 1.2, 'code': 2.0},
    'eid_al_fitr': {'month': 4, 'day': 15, 'default_entry_days_before': 15, 'default_exit_days_after': 3, 'default_weight': 1.0, 'code': 3.0},
    'christmas': {'month': 12, 'day': 25, 'default_entry_days_before': 15, 'default_exit_days_after': 3, 'default_weight': 0.8, 'code': 4.0},
}


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


def _build_holiday_calendar(index, params):
    calendar = []
    ts_index = pd.DatetimeIndex(index)
    years = sorted(ts_index.year.unique())
    for year in years:
        for holiday_name, holiday_def in HOLIDAY_DEFINITIONS.items():
            holiday_date = pd.Timestamp(datetime(year, holiday_def['month'], holiday_def['day']))
            if holiday_date < ts_index.min() or holiday_date > ts_index.max() + pd.Timedelta(days=40):
                continue
            pos = ts_index.searchsorted(holiday_date, side='left')
            if pos >= len(ts_index):
                pos = len(ts_index) - 1
            if pos < 0:
                continue
            event_date = ts_index[pos]
            entry_days = int(params.get(f'{holiday_name}_entry_days_before', holiday_def['default_entry_days_before']))
            exit_days = int(params.get(f'{holiday_name}_exit_days_after', holiday_def['default_exit_days_after']))
            weight = float(params.get(f'{holiday_name}_weight', holiday_def['default_weight']))
            start_pos = max(0, pos - entry_days)
            end_pos = min(len(ts_index) - 1, pos + exit_days)
            calendar.append({
                'holiday_name': holiday_name,
                'event_date': event_date,
                'start_pos': start_pos,
                'end_pos': end_pos,
                'weight': weight,
                'code': holiday_def['code'],
            })
    return calendar


def prepare_cultural_calendar_features(price_df, params):
    out = price_df.copy()
    base_position_size = float(params.get('base_position_size', 0.10))
    out['target_exposure'] = 0.0
    out['holiday_code'] = 0.0
    out['entry_signal'] = 0.0
    out['exit_signal'] = 0.0
    calendar = _build_holiday_calendar(out.index, params)
    for event in calendar:
        start_index = out.index[event['start_pos']]
        end_index = out.index[event['end_pos']]
        mask = (out.index >= start_index) & (out.index <= end_index)
        target = base_position_size * event['weight']
        current = out.loc[mask, 'target_exposure']
        stronger = target > current
        selected_index = current.index[stronger]
        if len(selected_index) > 0:
            out.loc[selected_index, 'target_exposure'] = target
            out.loc[selected_index, 'holiday_code'] = event['code']
        out.loc[start_index, 'entry_signal'] = max(float(out.loc[start_index, 'entry_signal']), target)
        out.loc[end_index, 'exit_signal'] = 1.0
    out['in_holiday_window'] = (out['target_exposure'] > 0).astype(float)
    out = out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'holiday_code', 'target_exposure', 'in_holiday_window', 'entry_signal', 'exit_signal',
    ]].copy()
    return out.dropna()


class CulturalCalendarGoldFeed(bt.feeds.PandasData):
    lines = ('holiday_code', 'target_exposure', 'in_holiday_window', 'entry_signal', 'exit_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('holiday_code', 6), ('target_exposure', 7), ('in_holiday_window', 8), ('entry_signal', 9), ('exit_signal', 10),
    )


class CulturalCalendarGoldStrategy(bt.Strategy):
    params = dict(
        base_position_size=0.10,
        diwali_entry_days_before=20,
        diwali_exit_days_after=5,
        diwali_weight=1.2,
        lunar_new_year_entry_days_before=20,
        lunar_new_year_exit_days_after=5,
        lunar_new_year_weight=1.2,
        eid_al_fitr_entry_days_before=15,
        eid_al_fitr_exit_days_after=3,
        eid_al_fitr_weight=1.0,
        christmas_entry_days_before=15,
        christmas_exit_days_after=3,
        christmas_weight=0.8,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.broker_value_series = []
        self.calendar_signal_days = 0
        self.max_target_exposure = 0.0

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        target = float(self.data.target_exposure[0])
        self.max_target_exposure = max(self.max_target_exposure, target)
        if target > 0:
            self.calendar_signal_days += 1
        if self.pending_order is not None:
            return
        current_target = max(0.0, min(1.0, target))
        current_position = abs(float(self.position.size))
        if self.position and float(self.data.exit_signal[0]) > 0.5 and current_target <= 0:
            self.sell_count += 1
            self.pending_order = self.order_target_percent(target=0.0)
            return
        if self.position and current_target <= 0:
            self.sell_count += 1
            self.pending_order = self.order_target_percent(target=0.0)
            return
        if current_target > 0:
            desired = current_target
            if not self.position:
                self.buy_count += 1
                self.pending_order = self.order_target_percent(target=desired)
                return
            self.pending_order = self.order_target_percent(target=desired)

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
