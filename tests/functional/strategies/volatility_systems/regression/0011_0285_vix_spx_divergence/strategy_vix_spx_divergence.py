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


def prepare_vix_spx_divergence_features(df, params):
    new_high_period = int(params.get('new_high_period', 50))
    vol_lookback = int(params.get('vol_lookback', 20))
    vol_rise_threshold = float(params.get('vol_rise_threshold', 0.02))
    corr_lookback = int(params.get('corr_lookback', 20))
    correlation_cutoff = float(params.get('correlation_cutoff', 0.3))
    monday_weight = float(params.get('monday_weight', 1.5))

    out = df.copy()
    ret = out['close'].pct_change()
    out['hist_vol'] = ret.rolling(vol_lookback).std() * np.sqrt(252)
    out['prev_hist_vol'] = out['hist_vol'].shift(1)
    out['vol_change'] = (out['hist_vol'] - out['prev_hist_vol']) / out['prev_hist_vol'].replace(0, np.nan)
    out['new_high'] = (out['close'] >= out['close'].rolling(new_high_period).max()).astype(float)
    out['vol_up'] = (out['vol_change'] > vol_rise_threshold).astype(float)
    out['price_vol_corr'] = ret.rolling(corr_lookback).corr(out['hist_vol'].pct_change())
    out['monday_flag'] = (pd.Index(out.index).weekday == 0).astype(float)
    out['signal_strength'] = 1.0
    out.loc[out['monday_flag'] > 0.5, 'signal_strength'] = monday_weight
    out.loc[out['vol_change'] > 0.05, 'signal_strength'] *= 1.3
    out['entry_signal'] = (
        (out['new_high'] > 0.5)
        & (out['vol_up'] > 0.5)
        & (out['price_vol_corr'] < correlation_cutoff)
    ).astype(float)
    out = out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'hist_vol', 'vol_change', 'new_high', 'vol_up', 'price_vol_corr', 'monday_flag',
        'signal_strength', 'entry_signal',
    ]].copy()
    return out.dropna()


class Mt5VixSpxDivergenceFeed(bt.feeds.PandasData):
    lines = (
        'hist_vol', 'vol_change', 'new_high', 'vol_up', 'price_vol_corr', 'monday_flag',
        'signal_strength', 'entry_signal',
    )
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('hist_vol', 6), ('vol_change', 7), ('new_high', 8), ('vol_up', 9), ('price_vol_corr', 10), ('monday_flag', 11),
        ('signal_strength', 12), ('entry_signal', 13),
    )


class VixSpxDivergenceStrategy(bt.Strategy):
    params = dict(
        holding_days=3,
        position_size=0.95,
        stop_loss=0.02,
        take_profit=0.015,
        new_high_period=50,
        vol_lookback=20,
        vol_rise_threshold=0.02,
        corr_lookback=20,
        correlation_cutoff=0.3,
        monday_weight=1.5,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_bar = 0
        self.stop_price = None
        self.take_profit_price = None
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        direction = 1.0 if target_notional_pct >= 0 else -1.0
        size = broker_value * abs(float(target_notional_pct)) / (execution_price * multiplier)
        return direction * round(size, 2)

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return

        low = float(self.data.low[0])
        high = float(self.data.high[0])
        close = float(self.data.close[0])

        if self.position:
            if self.stop_price is not None and high >= self.stop_price:
                self.buy_count += 1
                self.pending_order = self.close()
                return
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.buy_count += 1
                self.pending_order = self.close()
                return
            if self.bar_num - self.entry_bar >= int(self.p.holding_days):
                self.buy_count += 1
                self.pending_order = self.close()
                return
            return

        if float(self.data.entry_signal[0]) > 0.5:
            strength = min(float(self.data.signal_strength[0]), 1.5)
            target_pct = -float(self.p.position_size) * strength / 1.5
            self.sell_count += 1
            self.entry_bar = self.bar_num
            self.stop_price = close * (1.0 + float(self.p.stop_loss))
            self.take_profit_price = close * (1.0 - float(self.p.take_profit))
            target_size = self._get_position_size(target_notional_pct=target_pct)
            self.pending_order = self.order_target_size(target=target_size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.stop_price = None
            self.take_profit_price = None
