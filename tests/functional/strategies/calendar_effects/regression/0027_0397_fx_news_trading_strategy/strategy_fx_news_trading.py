from __future__ import absolute_import, division, print_function, unicode_literals

import io
from datetime import datetime

import backtrader as bt
import pandas as pd


EVENT_DEFINITIONS = {
    'nfp': {'month_day_rule': 'first_friday', 'code': 1.0},
    'fomc': {'fixed_dates': [(1, 31), (3, 20), (5, 1), (6, 12), (7, 31), (9, 18), (11, 7), (12, 18)], 'code': 2.0},
    'cpi': {'fixed_dates': [(1, 10), (2, 13), (3, 12), (4, 10), (5, 15), (6, 12), (7, 11), (8, 14), (9, 11), (10, 10), (11, 13), (12, 11)], 'code': 3.0},
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


def _first_friday(year, month):
    dates = pd.date_range(start=f'{year}-{month:02d}-01', end=f'{year}-{month:02d}-07', freq='D')
    fridays = [dt for dt in dates if dt.weekday() == 4]
    return fridays[0] if fridays else None


def _build_event_dates(index):
    ts_index = pd.DatetimeIndex(index)
    min_date = ts_index.min()
    max_date = ts_index.max()
    event_records = []
    for year in range(min_date.year, max_date.year + 1):
        for month in range(1, 13):
            nfp_date = _first_friday(year, month)
            if nfp_date is not None:
                event_records.append((nfp_date, EVENT_DEFINITIONS['nfp']['code']))
            for fixed_month, fixed_day in EVENT_DEFINITIONS['fomc']['fixed_dates']:
                if fixed_month == month:
                    event_records.append((pd.Timestamp(datetime(year, fixed_month, fixed_day)), EVENT_DEFINITIONS['fomc']['code']))
            for fixed_month, fixed_day in EVENT_DEFINITIONS['cpi']['fixed_dates']:
                if fixed_month == month:
                    event_records.append((pd.Timestamp(datetime(year, fixed_month, fixed_day)), EVENT_DEFINITIONS['cpi']['code']))
    aligned = []
    for event_date, code in event_records:
        if event_date < min_date or event_date > max_date:
            continue
        pos = ts_index.searchsorted(event_date, side='left')
        if pos >= len(ts_index):
            continue
        aligned.append((ts_index[pos], code))
    return aligned


def prepare_news_features(price_df, params):
    out = price_df.copy()
    lookback = int(params.get('volatility_lookback', 20))
    multiplier = float(params.get('volatility_multiplier', 1.0))
    total_risk = float(params.get('total_risk', 0.01))
    hold_days_after_event = int(params.get('hold_days_after_event', 3))
    event_window_days_before = int(params.get('event_window_days_before', 1))

    prev_close = out['close'].shift(1)
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - prev_close).abs(),
        (out['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out['volatility'] = tr.rolling(lookback).mean()
    out['event_code'] = 0.0
    out['event_window'] = 0.0
    out['buy_entry'] = float('nan')
    out['sell_entry'] = float('nan')
    out['stop_distance'] = float('nan')
    out['holding_days_target'] = 0.0

    for event_date, code in _build_event_dates(out.index):
        pos = out.index.get_loc(event_date)
        start_pos = max(0, pos - event_window_days_before)
        end_pos = min(len(out.index) - 1, pos + hold_days_after_event)
        window_index = out.index[start_pos:end_pos + 1]
        out.loc[window_index, 'event_code'] = float(code)
        out.loc[window_index, 'event_window'] = 1.0
        trigger_day = out.index[start_pos]
        if pd.isna(out.loc[trigger_day, 'volatility']):
            continue
        trigger_close = float(out.loc[trigger_day, 'close'])
        volatility = float(out.loc[trigger_day, 'volatility']) * multiplier
        out.loc[trigger_day, 'buy_entry'] = trigger_close + volatility
        out.loc[trigger_day, 'sell_entry'] = trigger_close - volatility
        out.loc[trigger_day, 'stop_distance'] = volatility * 2.0
        out.loc[trigger_day, 'holding_days_target'] = float(hold_days_after_event)

    out['risk_fraction'] = total_risk
    return out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'volatility', 'event_code', 'event_window', 'buy_entry', 'sell_entry', 'stop_distance', 'holding_days_target', 'risk_fraction',
    ]].dropna(subset=['volatility']).copy()


class FXNewsFeed(bt.feeds.PandasData):
    lines = ('volatility', 'event_code', 'event_window', 'buy_entry', 'sell_entry', 'stop_distance', 'holding_days_target', 'risk_fraction')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('volatility', 6), ('event_code', 7), ('event_window', 8), ('buy_entry', 9), ('sell_entry', 10), ('stop_distance', 11), ('holding_days_target', 12), ('risk_fraction', 13),
    )


class FXNewsTradingStrategy(bt.Strategy):
    params = dict(
        stop_loss_multiplier=1.0,
        volatility_lookback=20,
        volatility_multiplier=1.0,
        total_risk=0.01,
        hold_days_after_event=3,
        event_window_days_before=1,
        commission_pct=0.0002,
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
        self.entry_bar = None
        self.stop_price = None
        self.entry_side = 0
        self.event_days = 0

    def _position_size(self):
        stop_distance = float(self.data.stop_distance[0])
        if stop_distance <= 0:
            return 0.0
        risk_cash = float(self.broker.getvalue()) * float(self.data.risk_fraction[0])
        return max(0.01, round(risk_cash / stop_distance, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if float(self.data.event_window[0]) > 0.5:
            self.event_days += 1
        if self.pending_order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        if self.position:
            held = self.bar_num - (self.entry_bar or self.bar_num)
            if self.entry_side > 0 and self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.entry_side < 0 and self.stop_price is not None and high >= self.stop_price:
                self.buy_count += 1
                self.pending_order = self.close()
                return
            if held >= int(self.data.holding_days_target[0]) or float(self.data.event_window[0]) <= 0.5:
                if self.position.size > 0:
                    self.sell_count += 1
                elif self.position.size < 0:
                    self.buy_count += 1
                self.pending_order = self.close()
                return
            return
        if float(self.data.event_window[0]) <= 0.5:
            return
        size = self._position_size()
        if size <= 0:
            return
        buy_entry = float(self.data.buy_entry[0]) if self.data.buy_entry[0] == self.data.buy_entry[0] else None
        sell_entry = float(self.data.sell_entry[0]) if self.data.sell_entry[0] == self.data.sell_entry[0] else None
        if buy_entry is not None and high >= buy_entry:
            self.buy_count += 1
            self.entry_side = 1
            self.stop_price = float(self.data.sell_entry[0])
            self.entry_bar = self.bar_num
            self.pending_order = self.buy(size=size)
            return
        if sell_entry is not None and low <= sell_entry:
            self.sell_count += 1
            self.entry_side = -1
            self.stop_price = float(self.data.buy_entry[0])
            self.entry_bar = self.bar_num
            self.pending_order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed and not self.position:
            self.entry_bar = None
            self.stop_price = None
            self.entry_side = 0
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
