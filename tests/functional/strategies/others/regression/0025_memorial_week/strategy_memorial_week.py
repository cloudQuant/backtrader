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


def get_memorial_thursday(year):
    month_cal = calendar.monthcalendar(year, 5)
    last_monday = 0
    for week in reversed(month_cal):
        if week[calendar.MONDAY] != 0:
            last_monday = week[calendar.MONDAY]
            break
    memorial_monday = pd.Timestamp(year=year, month=5, day=last_monday)
    return memorial_monday + pd.Timedelta(days=3)


def prepare_memorial_week_features(price_df, params):
    out = price_df.copy()
    memorial_thursdays = {year: get_memorial_thursday(year) for year in out.index.year.unique()}
    entry_dates = pd.Index([memorial_thursdays[dt.year] for dt in out.index], dtype='datetime64[ns]')
    out['is_memorial_thursday'] = (pd.Index(out.index).normalize() == entry_dates).astype(float)
    out['entry_signal'] = out['is_memorial_thursday']
    return out


class MemorialWeekFeed(bt.feeds.PandasData):
    lines = ('is_memorial_thursday', 'entry_signal',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('is_memorial_thursday', 6),
        ('entry_signal', 7),
    )


class MemorialWeekStrategy(bt.Strategy):
    params = dict(
        holding_days=2,
        position_size=0.95,
        stop_loss=0.02,
        take_profit=0.015,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.signal_days = 0
        self.pending_order = None
        self.entry_bar = 0
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.broker_value_series = []

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return

        close = float(self.data.close[0])
        low = float(self.data.low[0])
        high = float(self.data.high[0])

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
            self.entry_price = close
            self.stop_price = close * (1.0 - float(self.p.stop_loss))
            self.take_profit_price = close * (1.0 + float(self.p.take_profit))
            self.pending_order = self.order_target_percent(target=float(self.p.position_size))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None
            self.take_profit_price = None
