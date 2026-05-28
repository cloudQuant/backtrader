from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
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


def prepare_simple_hedging_features(df, params):
    breakout_period = int(params.get('breakout_period', 10))
    max_holding_days = int(params.get('max_holding_days', 4))
    hedge_ratio = float(params.get('hedge_ratio', 0.95))

    frame = df.copy()
    frame['prior_low'] = frame['close'].rolling(breakout_period).min().shift(1)
    frame['breakout_signal'] = (frame['close'] < frame['prior_low']).astype(float)

    target_pct = []
    signal_change = []
    position = 0.0
    holding_days = 0
    prev_target = 0.0

    for row in frame.itertuples():
        breakout_signal = float(row.breakout_signal) > 0.5
        if position == 0.0:
            holding_days = 0
            if breakout_signal:
                position = -hedge_ratio
                holding_days = 1
        else:
            holding_days += 1
            if holding_days >= max_holding_days:
                position = 0.0
                holding_days = 0
        target_pct.append(position)
        signal_change.append(1.0 if position != prev_target else 0.0)
        prev_target = position

    frame['target_pct'] = target_pct
    frame['signal_change'] = signal_change
    feature_cols = ['open', 'high', 'low', 'close', 'volume', 'openinterest', 'prior_low', 'breakout_signal', 'target_pct', 'signal_change']
    return frame[feature_cols].dropna()


class SimpleHedgingFeed(bt.feeds.PandasData):
    lines = ('prior_low', 'breakout_signal', 'target_pct', 'signal_change')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('prior_low', 6), ('breakout_signal', 7), ('target_pct', 8), ('signal_change', 9),
    )


class SimpleHedgingTimeExitStrategy(bt.Strategy):
    params = dict(
        breakout_period=10,
        max_holding_days=4,
        hedge_ratio=0.95,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.pending_order = None
        self.bar_num = 0
        self.signal_change_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if float(self.data.signal_change[0]) <= 0.5:
            return
        self.signal_change_count += 1
        self.pending_order = self.order_target_percent(target=float(self.data.target_pct[0]))

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
