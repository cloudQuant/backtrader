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


def prepare_market_timing_data(df, params):
    out = df.copy()
    ma_period = int(params.get('ma_period', 200))
    confirm_days = int(params.get('confirm_days', 10))

    out['ma'] = out['close'].rolling(ma_period).mean()
    out['above_ma'] = (out['close'] > out['ma']).astype(float)
    out['below_ma'] = (out['close'] < out['ma']).astype(float)
    out['consecutive_above'] = out['above_ma'].rolling(confirm_days).sum()
    out['consecutive_below'] = out['below_ma'].rolling(confirm_days).sum()
    out['buy_signal'] = (out['consecutive_above'] >= confirm_days).astype(float)
    out['sell_signal'] = (out['consecutive_below'] >= confirm_days).astype(float)

    target = []
    current_target = 0.0
    for idx in out.index:
        if pd.isna(out.at[idx, 'ma']):
            target.append(current_target)
            continue
        if out.at[idx, 'buy_signal'] > 0.5:
            current_target = 1.0
        elif out.at[idx, 'sell_signal'] > 0.5:
            current_target = 0.0
        target.append(current_target)

    out['target_exposure'] = pd.Series(target, index=out.index, dtype='float64')
    out['signal_change'] = out['target_exposure'].ne(out['target_exposure'].shift(1)).astype(float)
    columns = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'ma', 'above_ma', 'consecutive_above', 'consecutive_below',
        'buy_signal', 'sell_signal', 'target_exposure', 'signal_change',
    ]
    return out[columns].copy().dropna()


class MarketTimingFeed(bt.feeds.PandasData):
    lines = ('ma', 'above_ma', 'consecutive_above', 'consecutive_below', 'buy_signal', 'sell_signal', 'target_exposure', 'signal_change')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('ma', 6), ('above_ma', 7), ('consecutive_above', 8), ('consecutive_below', 9),
        ('buy_signal', 10), ('sell_signal', 11), ('target_exposure', 12), ('signal_change', 13),
    )


class MarketTimingIndicatorComparisonStrategy(bt.Strategy):
    params = dict(
        invest_pct=0.99,
        ma_period=200,
        confirm_days=10,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.pending_order = None
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.signal_change_count = 0
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        if float(self.data.signal_change[0]) <= 0.5:
            return
        self.signal_change_count += 1
        target = float(self.data.target_exposure[0]) * float(self.p.invest_pct)
        self.pending_order = self.order_target_percent(target=target)

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
