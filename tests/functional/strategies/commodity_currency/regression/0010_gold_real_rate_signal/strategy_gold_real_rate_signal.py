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


def prepare_real_rate_signal_features(gold_df, nominal_df, inflation_df, params):
    common_index = gold_df.index.intersection(nominal_df.index).intersection(inflation_df.index).sort_values()
    gold = gold_df.loc[common_index].copy()
    nominal = nominal_df.loc[common_index].copy()
    inflation = inflation_df.loc[common_index].copy()

    signal_window = int(params.get('signal_window', 63))
    trend_window = int(params.get('trend_window', 126))
    entry_threshold = float(params.get('entry_threshold', 0.0))
    stop_loss_pct = float(params.get('stop_loss_pct', 0.08))
    base_position_pct = float(params.get('base_position_pct', 0.5))
    max_position_pct = float(params.get('max_position_pct', 1.0))
    vol_window = int(params.get('vol_window', 21))
    high_vol_threshold = float(params.get('high_vol_threshold', 0.25))

    signal_df = gold[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    signal_df['month'] = signal_df.index.month
    signal_df['rebalance_signal'] = (signal_df['month'] != signal_df['month'].shift(1)).astype(float)

    ratio = nominal['close'] / inflation['close']
    signal_df['real_rate_proxy'] = np.log(ratio)
    signal_df['real_rate_change'] = signal_df['real_rate_proxy'] - signal_df['real_rate_proxy'].shift(signal_window)
    signal_df['real_rate_trend'] = signal_df['real_rate_proxy'] - signal_df['real_rate_proxy'].rolling(trend_window).mean()
    signal_df['gold_volatility'] = gold['close'].pct_change().rolling(vol_window).std() * np.sqrt(252)
    rolling_peak = gold['close'].cummax()
    signal_df['gold_drawdown'] = gold['close'] / rolling_peak - 1.0

    position_sizes = []
    long_signal = []
    for _, row in signal_df.iterrows():
        rr_change = row['real_rate_change']
        rr_trend = row['real_rate_trend']
        vol = row['gold_volatility']
        drawdown = row['gold_drawdown']
        if pd.isna(rr_change) or pd.isna(rr_trend):
            long_signal.append(0.0)
            position_sizes.append(0.0)
            continue
        active = rr_change < entry_threshold and rr_trend < 0 and drawdown > -stop_loss_pct
        long_signal.append(float(active))
        if not active:
            position_sizes.append(0.0)
            continue
        strength = min(1.0, abs(rr_change) / max(1e-6, signal_df['real_rate_change'].abs().rolling(trend_window).mean().loc[row.name] or 1e-6))
        target_pct = base_position_pct + (max_position_pct - base_position_pct) * strength
        if pd.notna(vol) and vol > high_vol_threshold:
            target_pct *= 0.5
        position_sizes.append(max(0.0, min(max_position_pct, target_pct)))

    signal_df['long_signal'] = long_signal
    signal_df['target_pct'] = position_sizes
    return signal_df.dropna(subset=['real_rate_change', 'real_rate_trend'])


class GoldRealRateSignalFeed(bt.feeds.PandasData):
    lines = ('month', 'rebalance_signal', 'real_rate_proxy', 'real_rate_change', 'real_rate_trend', 'gold_volatility', 'gold_drawdown', 'long_signal', 'target_pct')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month', 6), ('rebalance_signal', 7), ('real_rate_proxy', 8), ('real_rate_change', 9), ('real_rate_trend', 10), ('gold_volatility', 11), ('gold_drawdown', 12), ('long_signal', 13), ('target_pct', 14),
    )


class GoldRealRateSignalStrategy(bt.Strategy):
    params = dict(
        signal_window=63,
        trend_window=126,
        entry_threshold=0.0,
        stop_loss_pct=0.08,
        base_position_pct=0.5,
        max_position_pct=1.0,
        vol_window=21,
        high_vol_threshold=0.25,
        rebalance_frequency='monthly',
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if float(self.data.rebalance_signal[0]) <= 0.5:
            return
        target_pct = float(self.data.target_pct[0]) if float(self.data.long_signal[0]) > 0.5 else 0.0
        current_size = self.position.size
        self.pending_order = self.order_target_percent(target=target_pct)
        if self.pending_order is not None:
            if target_pct > 0 and current_size <= 0:
                self.buy_count += 1
            elif target_pct == 0 and current_size > 0:
                self.sell_count += 1

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
