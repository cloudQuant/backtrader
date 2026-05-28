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


def prepare_momentum_strategy_data(df, params):
    out = df.copy()
    momentum_lookback = int(params.get('momentum_lookback', 252))
    trend_ma_period = int(params.get('trend_ma_period', 200))
    target_volatility = float(params.get('target_volatility', 0.15))
    vol_window = int(params.get('vol_window', 21))
    crash_lookback = int(params.get('crash_lookback', 21))
    crash_drawdown_threshold = float(params.get('crash_drawdown_threshold', -0.15))
    crash_vol_multiplier = float(params.get('crash_vol_multiplier', 2.0))
    base_invest_pct = float(params.get('base_invest_pct', 0.99))

    out['daily_return'] = out['close'].pct_change()
    out['momentum_return'] = out['close'].pct_change(momentum_lookback)
    out['momentum_signal'] = np.sign(out['momentum_return']).astype(float)
    out['trend_ma'] = out['close'].rolling(trend_ma_period).mean()
    out['trend_filter'] = np.where(out['close'] > out['trend_ma'], 1.0, -1.0)
    out['realized_vol'] = out['daily_return'].rolling(vol_window).std() * np.sqrt(252.0)
    out['recent_vol'] = out['daily_return'].rolling(crash_lookback).std() * np.sqrt(252.0)
    out['long_term_vol'] = out['daily_return'].rolling(momentum_lookback).std() * np.sqrt(252.0)
    out['recent_return'] = out['close'].pct_change(crash_lookback)
    out['crash_flag'] = ((out['recent_vol'] > out['long_term_vol'] * crash_vol_multiplier) | (out['recent_return'] < crash_drawdown_threshold)).astype(float)

    raw_exposure = out['momentum_signal'].copy()
    raw_exposure[(out['trend_filter'] < 0) & (raw_exposure > 0)] = raw_exposure[(out['trend_filter'] < 0) & (raw_exposure > 0)] * 0.5
    vol_scale = target_volatility / out['realized_vol'].replace(0.0, np.nan)
    vol_scale = vol_scale.clip(lower=0.0, upper=1.0).fillna(0.0)
    target_exposure = raw_exposure * vol_scale * base_invest_pct
    target_exposure[out['crash_flag'] > 0.5] = target_exposure[out['crash_flag'] > 0.5] * 0.3
    out['target_exposure'] = target_exposure.clip(lower=-base_invest_pct, upper=base_invest_pct)
    out['signal_change'] = out['target_exposure'].round(6).ne(out['target_exposure'].shift(1).round(6)).astype(float)

    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'momentum_return', 'momentum_signal', 'trend_ma', 'trend_filter',
        'realized_vol', 'recent_vol', 'long_term_vol', 'recent_return',
        'crash_flag', 'target_exposure', 'signal_change',
    ]
    return out[columns].copy().dropna()


class MomentumInsightsFeed(bt.feeds.PandasData):
    lines = ('momentum_return', 'momentum_signal', 'trend_ma', 'trend_filter', 'realized_vol', 'recent_vol', 'long_term_vol', 'recent_return', 'crash_flag', 'target_exposure', 'signal_change')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('momentum_return', 6), ('momentum_signal', 7), ('trend_ma', 8), ('trend_filter', 9), ('realized_vol', 10), ('recent_vol', 11), ('long_term_vol', 12), ('recent_return', 13), ('crash_flag', 14), ('target_exposure', 15), ('signal_change', 16),
    )


class MomentumStrategyInsightsStrategy(bt.Strategy):
    params = dict(
        momentum_lookback=252,
        trend_ma_period=200,
        target_volatility=0.15,
        vol_window=21,
        crash_lookback=21,
        crash_drawdown_threshold=-0.15,
        crash_vol_multiplier=2.0,
        base_invest_pct=0.99,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.pending_order = None
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
        self.pending_order = self.order_target_percent(target=float(self.data.target_exposure[0]))

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
