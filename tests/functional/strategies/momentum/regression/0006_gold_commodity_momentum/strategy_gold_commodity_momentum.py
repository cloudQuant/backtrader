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


def prepare_gold_commodity_momentum_features(price_df, params):
    short_lookback_months = int(params.get('short_lookback_months', 3))
    long_lookback_months = int(params.get('long_lookback_months', 12))
    breakout_window_days = int(params.get('breakout_window_days', 63))
    base_position_pct = float(params.get('base_position_pct', 0.05))
    min_position_pct = float(params.get('min_position_pct', 0.02))
    max_position_pct = float(params.get('max_position_pct', 0.20))
    target_vol = float(params.get('target_vol', 0.15))
    vol_lookback_days = int(params.get('vol_lookback_days', 63))
    atr_window_days = int(params.get('atr_window_days', 63))
    holding_months = int(params.get('holding_months', 3))
    allow_short = bool(params.get('allow_short', True))

    out = price_df.copy()
    monthly_close = out['close'].resample('ME').last()
    short_mom = monthly_close.pct_change(short_lookback_months)
    long_mom = monthly_close.pct_change(long_lookback_months)
    out['short_momentum'] = short_mom.reindex(out.index, method='ffill')
    out['long_momentum'] = long_mom.reindex(out.index, method='ffill')
    out['breakout_high'] = out['high'].shift(1).rolling(breakout_window_days).max()
    out['breakdown_low'] = out['low'].shift(1).rolling(breakout_window_days).min()
    out['daily_return'] = out['close'].pct_change()
    out['annual_vol'] = out['daily_return'].rolling(vol_lookback_days).std() * np.sqrt(252)
    true_range = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low'] - out['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out['atr_3m'] = true_range.rolling(atr_window_days).mean()

    both_up = (out['short_momentum'] > 0) & (out['long_momentum'] > 0) & (out['close'] > out['breakout_high'])
    both_down = (out['short_momentum'] < 0) & (out['long_momentum'] < 0) & (out['close'] < out['breakdown_low'])
    out['direction'] = 0.0
    out.loc[both_up, 'direction'] = 1.0
    if allow_short:
        out.loc[both_down, 'direction'] = -1.0

    strength = ((out['short_momentum'].abs().fillna(0.0) + out['long_momentum'].abs().fillna(0.0)) / 2.0).clip(lower=0.0, upper=1.0)
    vol_scale = (target_vol / out['annual_vol'].replace(0, np.nan)).clip(lower=0.5, upper=2.0).fillna(1.0)
    raw_target = (base_position_pct * strength * vol_scale).clip(lower=min_position_pct, upper=max_position_pct)
    out['target_pct'] = np.where(out['direction'] != 0, raw_target * out['direction'], 0.0)

    periods = pd.Series(out.index, index=out.index).dt.to_period('M')
    out['rebalance_flag'] = (periods != periods.shift(-1)).astype(float)
    month_ord = periods.astype(str).factorize()[0]
    last_signal_month = pd.Series(np.where(out['direction'] != 0, month_ord, np.nan), index=out.index).ffill()
    out['months_since_signal'] = month_ord - last_signal_month
    out['exit_signal'] = (((out['direction'] == 0) & (out['target_pct'] == 0)) | (out['months_since_signal'] >= holding_months)).astype(float)

    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'short_momentum', 'long_momentum', 'breakout_high', 'breakdown_low',
        'annual_vol', 'atr_3m', 'direction', 'target_pct', 'rebalance_flag', 'exit_signal'
    ]
    return out[cols].dropna(subset=['short_momentum', 'long_momentum', 'target_pct'])


class GoldCommodityMomentumFeed(bt.feeds.PandasData):
    lines = ('short_momentum', 'long_momentum', 'breakout_high', 'breakdown_low', 'annual_vol', 'atr_3m', 'direction', 'target_pct', 'rebalance_flag', 'exit_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('short_momentum', 6), ('long_momentum', 7), ('breakout_high', 8), ('breakdown_low', 9), ('annual_vol', 10), ('atr_3m', 11), ('direction', 12), ('target_pct', 13), ('rebalance_flag', 14), ('exit_signal', 15),
    )


class GoldCommodityMomentumStrategy(bt.Strategy):
    params = dict(
        atr_stop_multiplier=1.0,
        short_lookback_months=3,
        long_lookback_months=12,
        breakout_window_days=63,
        holding_months=3,
        allow_short=True,
        base_position_pct=0.05,
        min_position_pct=0.02,
        max_position_pct=0.2,
        target_vol=0.15,
        vol_lookback_days=63,
        atr_window_days=63,
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
        atr = float(self.data.atr_3m[0]) if self.data.atr_3m[0] == self.data.atr_3m[0] else 0.0
        if self.position:
            if self.entry_direction > 0 and self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.entry_direction < 0 and self.stop_price is not None and high >= self.stop_price:
                self.buy_count += 1
                self.pending_order = self.close()
                return
            if float(self.data.rebalance_flag[0]) > 0.5 and float(self.data.exit_signal[0]) > 0.5:
                if self.entry_direction > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
                self.pending_order = self.close()
                return
        if float(self.data.rebalance_flag[0]) <= 0.5:
            return
        target_pct = float(self.data.target_pct[0]) if self.data.target_pct[0] == self.data.target_pct[0] else 0.0
        if abs(target_pct) < 1e-8:
            return
        direction = 1 if target_pct > 0 else -1
        if self.position and self.entry_direction == direction:
            self.pending_order = self.order_target_percent(target=target_pct)
            return
        self.entry_direction = direction
        self.stop_price = close - float(self.p.atr_stop_multiplier) * atr if direction > 0 else close + float(self.p.atr_stop_multiplier) * atr
        if direction > 0:
            self.buy_count += 1
        else:
            self.sell_count += 1
        self.pending_order = self.order_target_percent(target=target_pct)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_direction = 0
            self.stop_price = None
