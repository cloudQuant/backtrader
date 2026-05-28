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


def prepare_gold_tsm_features(price_df, params):
    lookback_months = int(params.get('lookback_months', 12))
    strong_threshold = float(params.get('strong_threshold', 0.10))
    allow_short = bool(params.get('allow_short', False))
    vol_lookback = int(params.get('vol_lookback', 20))
    target_vol = float(params.get('target_vol', 0.15))
    min_position_scale = float(params.get('min_position_scale', 0.5))
    max_position_scale = float(params.get('max_position_scale', 1.5))

    out = price_df.copy()
    out['daily_return'] = out['close'].pct_change()
    out['annual_vol'] = out['daily_return'].rolling(vol_lookback).std() * np.sqrt(252)
    monthly_close = out['close'].resample('ME').last()
    monthly_momentum = monthly_close.pct_change(lookback_months)
    out['momentum_return'] = monthly_momentum.reindex(out.index, method='ffill')
    periods = pd.Series(out.index, index=out.index).dt.to_period('M')
    out['rebalance_flag'] = (periods != periods.shift(-1)).astype(float)
    vol_scale = (target_vol / out['annual_vol'].replace(0, np.nan)).clip(lower=min_position_scale, upper=max_position_scale)
    out['vol_scale'] = vol_scale.fillna(1.0)

    if allow_short:
        out['base_target'] = np.where(
            out['momentum_return'] > strong_threshold,
            1.0,
            np.where(
                out['momentum_return'] > 0,
                0.5,
                np.where(out['momentum_return'] < -strong_threshold, -1.0, np.where(out['momentum_return'] < 0, -0.5, 0.0)),
            ),
        )
    else:
        out['base_target'] = np.where(out['momentum_return'] > strong_threshold, 1.0, np.where(out['momentum_return'] > 0, 0.5, 0.0))
    out['target_pct'] = out['base_target'] * out['vol_scale']
    cols = ['open', 'high', 'low', 'close', 'volume', 'openinterest', 'momentum_return', 'annual_vol', 'vol_scale', 'target_pct', 'rebalance_flag']
    return out[cols].dropna(subset=['momentum_return', 'target_pct'])


class GoldTimeSeriesMomentumFeed(bt.feeds.PandasData):
    lines = ('momentum_return', 'annual_vol', 'vol_scale', 'target_pct', 'rebalance_flag')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('momentum_return', 6), ('annual_vol', 7), ('vol_scale', 8), ('target_pct', 9), ('rebalance_flag', 10),
    )


class GoldTimeSeriesMomentumStrategy(bt.Strategy):
    params = dict(
        stop_loss_pct=0.08,
        lookback_months=12,
        strong_threshold=0.1,
        allow_short=False,
        vol_lookback=20,
        target_vol=0.15,
        min_position_scale=0.5,
        max_position_scale=1.5,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_direction = 0
        self.stop_price = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        close = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position:
            if self.entry_direction > 0 and self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.entry_direction < 0 and self.stop_price is not None and high >= self.stop_price:
                self.buy_count += 1
                self.pending_order = self.close()
                return
        if float(self.data.rebalance_flag[0]) < 0.5:
            return
        target_pct = float(self.data.target_pct[0]) if self.data.target_pct[0] == self.data.target_pct[0] else 0.0
        current_size = float(self.position.size)
        if abs(target_pct) < 1e-8:
            if current_size != 0:
                if current_size > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
                self.pending_order = self.close()
            return
        direction = 1 if target_pct > 0 else -1
        if current_size == 0 or (current_size > 0 and direction < 0) or (current_size < 0 and direction > 0):
            if direction > 0:
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.entry_direction = direction
        self.stop_price = close * (1.0 - float(self.p.stop_loss_pct)) if direction > 0 else close * (1.0 + float(self.p.stop_loss_pct))
        self.pending_order = self.order_target_percent(target=target_pct)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_direction = 0
            self.stop_price = None
