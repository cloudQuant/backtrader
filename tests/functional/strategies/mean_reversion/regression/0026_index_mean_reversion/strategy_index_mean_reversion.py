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


def prepare_index_mean_reversion_data(df, params):
    out = df.copy()
    weekly_lookback = int(params.get('weekly_lookback', 5))
    signal_delay_days = int(params.get('signal_delay_days', 1))
    ma_period = int(params.get('ma_period', 200))
    vol_window = int(params.get('vol_window', 20))
    vol_threshold = float(params.get('vol_threshold', 0.25))
    base_invest_pct = float(params.get('base_invest_pct', 0.99))
    use_trend_filter = bool(params.get('use_trend_filter', True))
    use_vol_filter = bool(params.get('use_vol_filter', True))

    out['weekly_return'] = out['close'].pct_change(weekly_lookback)
    out['ma'] = out['close'].rolling(ma_period).mean()
    out['trend'] = np.where(out['close'] > out['ma'], 1.0, -1.0)
    out['daily_return'] = out['close'].pct_change()
    out['volatility'] = out['daily_return'].rolling(vol_window).std() * np.sqrt(252.0)
    out['vol_multiplier'] = 1.0
    if use_vol_filter:
        out.loc[out['volatility'] > vol_threshold, 'vol_multiplier'] = 0.5

    week_period = pd.Series(out.index, index=out.index).dt.to_period('W-FRI')
    is_week_end = week_period != week_period.shift(-1)
    out['week_end_flag'] = is_week_end.astype(float)

    scheduled_signal = pd.Series(np.nan, index=out.index, dtype='float64')
    for idx in out.index[out['week_end_flag'] > 0.5]:
        weekly_ret = out.at[idx, 'weekly_return']
        trend = out.at[idx, 'trend']
        vol_multiplier = out.at[idx, 'vol_multiplier']
        if pd.isna(weekly_ret):
            continue
        mr_signal = -np.sign(weekly_ret)
        if mr_signal == 0:
            target = 0.0
        else:
            if use_trend_filter:
                if mr_signal > 0 and trend > 0:
                    target = base_invest_pct
                elif mr_signal < 0 and trend < 0:
                    target = -base_invest_pct
                else:
                    target = mr_signal * base_invest_pct * 0.5
            else:
                target = mr_signal * base_invest_pct
            target *= vol_multiplier
        scheduled_signal.at[idx] = target

    out['target_exposure'] = scheduled_signal.shift(signal_delay_days).ffill().fillna(0.0)
    out['signal_change'] = out['target_exposure'].ne(out['target_exposure'].shift(1)).astype(float)
    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'weekly_return', 'ma', 'trend', 'volatility', 'vol_multiplier',
        'week_end_flag', 'target_exposure', 'signal_change',
    ]
    return out[columns].copy().dropna()


class IndexMeanReversionFeed(bt.feeds.PandasData):
    lines = ('weekly_return', 'ma', 'trend', 'volatility', 'vol_multiplier', 'week_end_flag', 'target_exposure', 'signal_change')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('weekly_return', 6), ('ma', 7), ('trend', 8), ('volatility', 9), ('vol_multiplier', 10), ('week_end_flag', 11), ('target_exposure', 12), ('signal_change', 13),
    )


class IndexMeanReversionStrategy(bt.Strategy):
    params = dict(
        weekly_lookback=5,
        signal_delay_days=1,
        ma_period=200,
        vol_window=20,
        vol_threshold=0.25,
        base_invest_pct=0.99,
        use_trend_filter=True,
        use_vol_filter=True,
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
