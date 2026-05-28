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


def rolling_percentile(series, window):
    return series.rolling(window).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)


def prepare_ratio_features(gold_df, djia_df, params):
    common_index = gold_df.index.intersection(djia_df.index).sort_values()
    gold = gold_df.loc[common_index].copy()
    djia = djia_df.loc[common_index].copy()

    short_ma_window = int(params.get('short_ma_window', 50))
    long_ma_window = int(params.get('long_ma_window', 200))
    percentile_window = int(params.get('percentile_window', 504))
    upper_percentile = float(params.get('upper_percentile', 0.7))
    lower_percentile = float(params.get('lower_percentile', 0.3))
    gold_momentum_window = int(params.get('gold_momentum_window', 63))
    rebalance_frequency = str(params.get('rebalance_frequency', 'weekly')).lower()

    out = gold[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    out['gold_djia_ratio'] = gold['close'] / djia['close']
    out['ratio_ma_short'] = out['gold_djia_ratio'].rolling(short_ma_window).mean()
    out['ratio_ma_long'] = out['gold_djia_ratio'].rolling(long_ma_window).mean()
    out['ratio_percentile'] = rolling_percentile(out['gold_djia_ratio'], percentile_window)
    out['gold_momentum'] = gold['close'].pct_change(gold_momentum_window)

    trend_up = out['ratio_ma_short'] > out['ratio_ma_long']
    strong_ratio = out['ratio_percentile'] >= upper_percentile
    weak_ratio = out['ratio_percentile'] <= lower_percentile
    positive_momentum = out['gold_momentum'] > 0

    out['long_signal'] = (trend_up & strong_ratio & positive_momentum).astype(float)
    out['exit_signal'] = ((~trend_up) | weak_ratio | (~positive_momentum)).astype(float)
    out['target_pct'] = np.where(out['long_signal'] > 0.5, 1.0, 0.0)

    if rebalance_frequency == 'weekly':
        week_key = out.index.to_period('W-FRI')
        out['rebalance_signal'] = (week_key != week_key.shift(1)).astype(float)
    elif rebalance_frequency == 'monthly':
        month_key = out.index.to_period('M')
        out['rebalance_signal'] = (month_key != month_key.shift(1)).astype(float)
    else:
        out['rebalance_signal'] = 1.0

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 'gold_djia_ratio', 'ratio_ma_short', 'ratio_ma_long', 'ratio_percentile', 'gold_momentum', 'long_signal', 'exit_signal', 'target_pct', 'rebalance_signal']].copy()
    return out.dropna(subset=['ratio_ma_long', 'ratio_percentile', 'gold_momentum'])


class DJIAGoldRatioFeed(bt.feeds.PandasData):
    lines = ('gold_djia_ratio', 'ratio_ma_short', 'ratio_ma_long', 'ratio_percentile', 'gold_momentum', 'long_signal', 'exit_signal', 'target_pct', 'rebalance_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('gold_djia_ratio', 6), ('ratio_ma_short', 7), ('ratio_ma_long', 8), ('ratio_percentile', 9), ('gold_momentum', 10), ('long_signal', 11), ('exit_signal', 12), ('target_pct', 13), ('rebalance_signal', 14),
    )


class DJIAGoldRatioStrategy(bt.Strategy):
    params = dict(
        short_ma_window=50,
        long_ma_window=200,
        percentile_window=504,
        upper_percentile=0.7,
        lower_percentile=0.3,
        gold_momentum_window=63,
        rebalance_frequency='weekly',
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
