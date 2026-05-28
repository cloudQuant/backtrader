from __future__ import absolute_import, division, print_function, unicode_literals

import io
import zipfile
import urllib.request

import backtrader as bt
import numpy as np
import pandas as pd


LEGACY_COLUMNS = [
    'market_and_exchange_names', 'as_of_date_yy', 'report_date', 'contract_market_code',
    'market_code', 'region_code', 'commodity_code', 'open_interest_all',
    'noncommercial_long_all', 'noncommercial_short_all', 'noncommercial_spreading_all',
    'commercial_long_all', 'commercial_short_all', 'total_reportable_long_all',
    'total_reportable_short_all', 'nonreportable_long_all', 'nonreportable_short_all'
]


def fetch_text_from_url(url):
    request = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/plain,text/csv,text/html,*/*',
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode('utf-8', errors='ignore')


def fetch_bytes_from_url(url):
    request = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/zip,application/octet-stream,*/*',
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def load_legacy_cot_year(year):
    zip_url = f'https://www.cftc.gov/files/dea/history/deacot{year}.zip'
    zip_bytes = fetch_bytes_from_url(zip_url)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(('.txt', '.csv'))]
        if not members:
            raise ValueError(f'No text member found in {zip_url}')
        text = archive.read(members[0]).decode('utf-8', errors='ignore')
    return pd.read_csv(io.StringIO(text), header=None, usecols=range(len(LEGACY_COLUMNS)), names=LEGACY_COLUMNS, skipinitialspace=True, dtype=str, low_memory=False)


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


def resample_to_weekly(df):
    weekly = pd.DataFrame({
        'open': df['open'].resample('W-FRI').first(),
        'high': df['high'].resample('W-FRI').max(),
        'low': df['low'].resample('W-FRI').min(),
        'close': df['close'].resample('W-FRI').last(),
        'volume': df['volume'].resample('W-FRI').sum(),
        'openinterest': df['openinterest'].resample('W-FRI').last().fillna(0),
    })
    return weekly.dropna(subset=['open', 'high', 'low', 'close'])


def load_cot_legacy_gold(cot_url, market_name, exclude_name=None, start_year=None, end_year=None):
    del cot_url
    if start_year is None or end_year is None:
        raise ValueError('start_year and end_year are required for historical COT loading')
    yearly_frames = [load_legacy_cot_year(year) for year in range(int(start_year), int(end_year) + 1)]
    cot = pd.concat(yearly_frames, ignore_index=True)
    cot['market_and_exchange_names'] = cot['market_and_exchange_names'].astype(str).str.strip()
    cot = cot[cot['market_and_exchange_names'].str.contains(market_name, na=False)]
    if exclude_name:
        cot = cot[~cot['market_and_exchange_names'].str.contains(exclude_name, na=False)]
    cot['report_date'] = pd.to_datetime(cot['report_date'])
    cot['release_date'] = cot['report_date'] + pd.to_timedelta((4 - cot['report_date'].dt.weekday) % 7, unit='D')
    numeric_cols = [
        'open_interest_all', 'noncommercial_long_all', 'noncommercial_short_all',
        'commercial_long_all', 'commercial_short_all'
    ]
    for col in numeric_cols:
        cot[col] = pd.to_numeric(cot[col], errors='coerce')
    cot['commercial_net'] = cot['commercial_long_all'] - cot['commercial_short_all']
    cot['speculator_net'] = cot['noncommercial_long_all'] - cot['noncommercial_short_all']
    cot = cot[['release_date', 'open_interest_all', 'commercial_net', 'speculator_net']].dropna().drop_duplicates(subset=['release_date']).set_index('release_date').sort_index()
    return cot


def prepare_gold_cot_features(price_df, cot_df, params):
    weekly_price = resample_to_weekly(price_df)
    cot_weekly = cot_df.copy()
    common_index = weekly_price.index.intersection(cot_weekly.index).sort_values()
    out = weekly_price.loc[common_index].copy()
    cot_weekly = cot_weekly.loc[common_index].copy()
    zscore_window = int(params.get('zscore_window_weeks', 156))
    extreme_threshold = float(params.get('extreme_threshold', 2.0))
    exit_threshold = float(params.get('exit_threshold', 1.0))
    commercial_mean = cot_weekly['commercial_net'].rolling(zscore_window).mean()
    commercial_std = cot_weekly['commercial_net'].rolling(zscore_window).std().replace(0, np.nan)
    spec_mean = cot_weekly['speculator_net'].rolling(zscore_window).mean()
    spec_std = cot_weekly['speculator_net'].rolling(zscore_window).std().replace(0, np.nan)
    out['commercial_net'] = cot_weekly['commercial_net']
    out['speculator_net'] = cot_weekly['speculator_net']
    out['open_interest_all'] = cot_weekly['open_interest_all']
    out['commercial_z'] = (cot_weekly['commercial_net'] - commercial_mean) / commercial_std
    out['speculator_z'] = (cot_weekly['speculator_net'] - spec_mean) / spec_std
    out['entry_signal'] = 0.0
    out['exit_signal'] = 0.0
    out['direction'] = 0.0
    out['position_scale'] = 0.0
    long_entry = (out['commercial_z'] >= extreme_threshold) & (out['speculator_z'] <= -extreme_threshold)
    short_entry = (out['commercial_z'] <= -extreme_threshold) & (out['speculator_z'] >= extreme_threshold)
    long_exit = (out['commercial_z'] < exit_threshold) & (out['speculator_z'] > -exit_threshold)
    short_exit = (out['commercial_z'] > -exit_threshold) & (out['speculator_z'] < exit_threshold)
    out.loc[long_entry, 'entry_signal'] = 1.0
    out.loc[long_entry, 'direction'] = 1.0
    out.loc[short_entry, 'entry_signal'] = 1.0
    out.loc[short_entry, 'direction'] = -1.0
    out.loc[long_exit | short_exit, 'exit_signal'] = 1.0
    extreme_strength = np.maximum(out['commercial_z'].abs(), out['speculator_z'].abs())
    out['position_scale'] = (extreme_strength / extreme_threshold).clip(lower=0.0)
    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'open_interest_all', 'commercial_net', 'speculator_net',
        'commercial_z', 'speculator_z', 'entry_signal', 'exit_signal', 'direction', 'position_scale'
    ]
    return out[cols].dropna(subset=['commercial_z', 'speculator_z'])


class GoldCotFeed(bt.feeds.PandasData):
    lines = (
        'open_interest_all', 'commercial_net', 'speculator_net',
        'commercial_z', 'speculator_z', 'entry_signal', 'exit_signal', 'direction', 'position_scale'
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('open_interest_all', 6), ('commercial_net', 7), ('speculator_net', 8),
        ('commercial_z', 9), ('speculator_z', 10), ('entry_signal', 11), ('exit_signal', 12), ('direction', 13), ('position_scale', 14),
    )


class GoldCotStrategy(bt.Strategy):
    params = dict(
        extreme_threshold=2.0,
        base_position_pct=0.03,
        max_position_pct=0.05,
        stop_loss_pct=0.03,
        allow_short=False,
        pause_after_losses=3,
        pause_weeks_after_losses=4,
        zscore_window_weeks=156,
        exit_threshold=1.0,
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
        self.stop_price = None
        self.pause_bars_remaining = 0
        self.consecutive_losses = 0
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) / execution_price
        return max(0.01, round(size, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if self.pause_bars_remaining > 0 and not self.position:
            self.pause_bars_remaining -= 1
            return
        entry_signal = float(self.data.entry_signal[0]) > 0.5
        exit_signal = float(self.data.exit_signal[0]) > 0.5
        direction = int(round(float(self.data.direction[0]))) if self.data.direction[0] == self.data.direction[0] else 0
        position_scale = float(self.data.position_scale[0]) if self.data.position_scale[0] == self.data.position_scale[0] else 0.0
        target_pct = min(float(self.p.max_position_pct), float(self.p.base_position_pct) * position_scale)
        if not self.position:
            if not entry_signal or direction == 0:
                return
            if direction < 0 and not bool(self.p.allow_short):
                return
            size = self._get_position_size(target_notional_pct=target_pct)
            if direction > 0:
                self.buy_count += 1
                self.pending_order = self.buy(size=size)
                self.stop_price = float(self.data.close[0]) * (1.0 - float(self.p.stop_loss_pct))
            else:
                self.sell_count += 1
                self.pending_order = self.sell(size=size)
                self.stop_price = float(self.data.close[0]) * (1.0 + float(self.p.stop_loss_pct))
            self.entry_price = float(self.data.close[0])
            self.entry_direction = direction
            return
        if self.entry_direction > 0 and self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
            self.sell_count += 1
            self.pending_order = self.close()
            return
        if self.entry_direction < 0 and self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
            self.buy_count += 1
            self.pending_order = self.close()
            return
        if exit_signal:
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
        self.stop_price = None
        if trade.pnlcomm >= 0:
            self.win_count += 1
            self.consecutive_losses = 0
        else:
            self.loss_count += 1
            self.consecutive_losses += 1
            if self.consecutive_losses >= int(self.p.pause_after_losses):
                self.pause_bars_remaining = int(self.p.pause_weeks_after_losses)
                self.consecutive_losses = 0
