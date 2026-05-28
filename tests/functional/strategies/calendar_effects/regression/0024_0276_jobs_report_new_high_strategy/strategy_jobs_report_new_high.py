from __future__ import absolute_import, division, print_function, unicode_literals

import calendar
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


def is_first_friday(ts):
    month_calendar = calendar.monthcalendar(ts.year, ts.month)
    first_friday = month_calendar[0][calendar.FRIDAY]
    if first_friday == 0:
        first_friday = month_calendar[1][calendar.FRIDAY]
    return ts.day == first_friday


def prepare_jobs_report_new_high_features(df, params):
    out = df.copy()
    new_high_period = int(params.get('new_high_period', 20))
    min_gain_pct = float(params.get('min_gain_pct', 0.005))

    out['daily_return'] = out['close'].pct_change()
    out['jobs_report_day'] = pd.Index(out.index).map(is_first_friday).astype(float)
    out['prior_high'] = out['close'].rolling(new_high_period).max().shift(1)
    out['is_new_high'] = (out['close'] > out['prior_high']).astype(float)
    out['strong_up_day'] = (out['daily_return'] >= min_gain_pct).astype(float)
    out['entry_signal'] = (
        (out['jobs_report_day'] > 0.5)
        & (out['is_new_high'] > 0.5)
        & (out['strong_up_day'] > 0.5)
    ).astype(float)
    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'daily_return', 'jobs_report_day', 'prior_high', 'is_new_high', 'strong_up_day', 'entry_signal',
    ]
    return out[cols].dropna()


class JobsReportNewHighFeed(bt.feeds.PandasData):
    lines = ('daily_return', 'jobs_report_day', 'prior_high', 'is_new_high', 'strong_up_day', 'entry_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('daily_return', 6), ('jobs_report_day', 7), ('prior_high', 8), ('is_new_high', 9), ('strong_up_day', 10), ('entry_signal', 11),
    )


class JobsReportNewHighStrategy(bt.Strategy):
    params = dict(
        holding_days=3,
        take_profit=0.015,
        stop_loss=0.01,
        position_size=0.95,
        new_high_period=20,
        min_gain_pct=0.005,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.signal_days = 0
        self.pending_order = None
        self.entry_bar = 0
        self.stop_price = None
        self.take_profit_price = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return

        low = float(self.data.low[0])
        high = float(self.data.high[0])
        close = float(self.data.close[0])

        if self.position:
            if self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.bar_num - self.entry_bar >= int(self.p.holding_days):
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return

        if float(self.data.entry_signal[0]) > 0.5:
            self.signal_days += 1
            self.buy_count += 1
            self.entry_bar = self.bar_num
            self.stop_price = close * (1.0 - float(self.p.stop_loss))
            self.take_profit_price = close * (1.0 + float(self.p.take_profit))
            self.pending_order = self.order_target_percent(target=float(self.p.position_size))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.stop_price = None
            self.take_profit_price = None
