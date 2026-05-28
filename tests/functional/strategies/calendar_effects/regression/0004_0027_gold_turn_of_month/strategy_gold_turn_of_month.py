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


def prepare_turn_of_month_features(price_df, params):
    days_n = int(params.get('turn_of_month_days', 5))
    special_months = set(int(v) for v in params.get('special_months', [5, 6, 8, 11]))
    special_days = set(int(v) for v in params.get('special_days', [1, 2, 3, 10, 11, 12]))
    out = price_df.copy()
    next_period = pd.Series(out.index, index=out.index).shift(-1).dt.to_period('M')
    current_period = pd.Series(out.index, index=out.index).dt.to_period('M')
    rev_rank = pd.Series(range(len(out)), index=out.index).groupby(current_period).transform(lambda x: x.rank(ascending=False, method='first'))
    out['is_turn_of_month'] = (rev_rank <= days_n).astype(float)
    out['is_special_day'] = pd.Series([(idx.month in special_months and idx.day in special_days) for idx in out.index], index=out.index).astype(float)
    out['entry_signal'] = ((out['is_turn_of_month'] > 0) | (out['is_special_day'] > 0)).astype(float)
    out['exit_signal'] = (((out['is_turn_of_month'] <= 0) & (out['is_special_day'] <= 0)) | (current_period != next_period.shift(1))).astype(float)
    return out


class GoldTurnOfMonthFeed(bt.feeds.PandasData):
    lines = ('is_turn_of_month', 'is_special_day', 'entry_signal', 'exit_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('is_turn_of_month', 6), ('is_special_day', 7), ('entry_signal', 8), ('exit_signal', 9),
    )


class GoldTurnOfMonthStrategy(bt.Strategy):
    params = dict(
        stop_loss_pct=0.02,
        turn_of_month_days=5,
        special_months=[5, 6, 8, 11],
        special_days=[1, 2, 3, 10, 11, 12],
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_price = None
        self.stop_price = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        close = float(self.data.close[0])
        low = float(self.data.low[0])
        if self.position:
            if self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if float(self.data.exit_signal[0]) > 0.5:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return
        if float(self.data.entry_signal[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.order_target_percent(target=1.0)
            self.entry_price = close
            self.stop_price = close * (1.0 - float(self.p.stop_loss_pct))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None
