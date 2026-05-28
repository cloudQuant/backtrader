from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    if bar_shift_minutes:
        parsed = parsed + pd.to_timedelta(int(bar_shift_minutes), unit='m')
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


def prepare_rotation_data(asset_daily_frames, params):
    monthly_frames = {name: resample_to_monthly(frame) for name, frame in asset_daily_frames.items()}
    common_index = None
    for frame in monthly_frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    common_index = common_index.sort_values()
    monthly_frames = {name: frame.loc[common_index].copy() for name, frame in monthly_frames.items()}

    w3 = float(params.get('momentum_3m_weight', 0.3))
    w6 = float(params.get('momentum_6m_weight', 0.3))
    w12 = float(params.get('momentum_12m_weight', 0.4))
    threshold = float(params.get('absolute_momentum_threshold', 0.0))
    confirm_months = int(params.get('switch_confirmation_months', 2))

    closes = pd.DataFrame({name: frame['close'] for name, frame in monthly_frames.items()}, index=common_index)
    momentum_3m = closes / closes.shift(3) - 1.0
    momentum_6m = closes / closes.shift(6) - 1.0
    momentum_12m = closes / closes.shift(12) - 1.0
    composite = w3 * momentum_3m + w6 * momentum_6m + w12 * momentum_12m

    target_asset = []
    pending_asset = None
    pending_count = 0
    active_asset = 'CASH'

    for idx in composite.index:
        scores = composite.loc[idx].dropna().sort_values(ascending=False)
        if scores.empty or float(scores.iloc[0]) <= threshold:
            candidate = 'CASH'
        else:
            candidate = str(scores.index[0])
        if candidate == active_asset:
            pending_asset = None
            pending_count = 0
        else:
            if candidate == pending_asset:
                pending_count += 1
            else:
                pending_asset = candidate
                pending_count = 1
            if pending_count >= confirm_months:
                active_asset = candidate
                pending_asset = None
                pending_count = 0
        target_asset.append(active_asset)

    summary = pd.DataFrame(index=common_index)
    summary['selected_asset'] = target_asset
    summary['selected_asset_code'] = pd.Series(target_asset, index=common_index).map({'CASH': 0, 'XAUUSD': 1, 'IVV': 2, 'IEF': 3, 'DBC': 4}).fillna(0).astype(float)
    summary['selected_momentum'] = [composite.loc[idx, asset] if asset in composite.columns else np.nan for idx, asset in zip(common_index, target_asset)]
    summary['cash_flag'] = (summary['selected_asset'] == 'CASH').astype(float)
    summary['xau_momentum'] = composite['XAUUSD']
    summary['ivv_momentum'] = composite['IVV']
    summary['ief_momentum'] = composite['IEF']
    summary['dbc_momentum'] = composite['DBC']
    signal_df = monthly_frames['XAUUSD'][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['selected_asset_code'] = summary['selected_asset_code']
    signal_df['selected_momentum'] = summary['selected_momentum']
    signal_df['cash_flag'] = summary['cash_flag']
    signal_df['xau_momentum'] = summary['xau_momentum']
    signal_df['ivv_momentum'] = summary['ivv_momentum']
    signal_df['ief_momentum'] = summary['ief_momentum']
    signal_df['dbc_momentum'] = summary['dbc_momentum']
    signal_df = signal_df.dropna(subset=['xau_momentum', 'ivv_momentum', 'ief_momentum', 'dbc_momentum'])
    monthly_frames = {name: frame.loc[signal_df.index].copy() for name, frame in monthly_frames.items()}
    summary = summary.loc[signal_df.index].copy()
    return signal_df, monthly_frames, summary


class GoldMomentumRotationSignalFeed(bt.feeds.PandasData):
    lines = ('selected_asset_code', 'selected_momentum', 'cash_flag', 'xau_momentum', 'ivv_momentum', 'ief_momentum', 'dbc_momentum')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('selected_asset_code', 6), ('selected_momentum', 7), ('cash_flag', 8), ('xau_momentum', 9), ('ivv_momentum', 10), ('ief_momentum', 11), ('dbc_momentum', 12),
    )


class GoldMomentumRotationStrategy(bt.Strategy):
    params = dict(
        cash_symbol='CASH',
        momentum_3m_weight=0.3,
        momentum_6m_weight=0.3,
        momentum_12m_weight=0.4,
        top_n=1,
        switch_confirmation_months=2,
        absolute_momentum_threshold=0.0,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.signal = self.datas[0]
        self.asset_map = {'XAUUSD': self.getdatabyname('XAUUSD'), 'IVV': self.getdatabyname('IVV'), 'IEF': self.getdatabyname('IEF'), 'DBC': self.getdatabyname('DBC')}
        self.code_to_asset = {0: 'CASH', 1: 'XAUUSD', 2: 'IVV', 3: 'IEF', 4: 'DBC'}
        self.bar_num = 0
        self.rebalance_count = 0
        self.switch_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order_refs = set()
        self.last_selected_asset = None
        self.broker_value_series = []
        self.cash_month_count = 0
        self.xau_month_count = 0
        self.ivv_month_count = 0
        self.ief_month_count = 0
        self.dbc_month_count = 0

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.signal.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order_refs:
            return
        asset_code = int(round(float(self.signal.selected_asset_code[0]))) if self.signal.selected_asset_code[0] == self.signal.selected_asset_code[0] else 0
        selected_asset = self.code_to_asset.get(asset_code, 'CASH')
        if selected_asset == 'CASH':
            self.cash_month_count += 1
        elif selected_asset == 'XAUUSD':
            self.xau_month_count += 1
        elif selected_asset == 'IVV':
            self.ivv_month_count += 1
        elif selected_asset == 'IEF':
            self.ief_month_count += 1
        elif selected_asset == 'DBC':
            self.dbc_month_count += 1
        if self.last_selected_asset == selected_asset:
            return
        if self.last_selected_asset is not None:
            self.switch_count += 1
        self.last_selected_asset = selected_asset
        self.rebalance_count += 1
        for asset_name, data in self.asset_map.items():
            target = 1.0 if asset_name == selected_asset else 0.0
            current_position = self.getposition(data).size
            order = self.order_target_percent(data=data, target=target)
            if order is not None:
                self.pending_order_refs.add(order.ref)
                if target > 0 and current_position <= 0:
                    self.buy_count += 1
                elif target == 0 and current_position > 0:
                    self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order_refs.discard(order.ref)
