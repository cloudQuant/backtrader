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


def prepare_gold_seasonal_windows_features(df, params):
    spring_entry_month = int(params.get('spring_entry_month', 3))
    spring_entry_td = int(params.get('spring_entry_td', 10))
    spring_exit_month = int(params.get('spring_exit_month', 6))
    spring_exit_td = int(params.get('spring_exit_td', 2))
    autumn_entry_month = int(params.get('autumn_entry_month', 10))
    autumn_entry_td = int(params.get('autumn_entry_td', 12))
    autumn_exit_month = int(params.get('autumn_exit_month', 11))
    autumn_exit_td = int(params.get('autumn_exit_td', 19))

    out = df.copy()
    out['year'] = out.index.year
    out['month'] = out.index.month
    out['trading_day'] = out.groupby([out.index.year, out.index.month]).cumcount() + 1

    spring_entry = (out['month'] == spring_entry_month) & (out['trading_day'] == spring_entry_td)
    spring_exit = (out['month'] == spring_exit_month) & (out['trading_day'] == spring_exit_td)
    autumn_entry = (out['month'] == autumn_entry_month) & (out['trading_day'] == autumn_entry_td)
    autumn_exit = (out['month'] == autumn_exit_month) & (out['trading_day'] == autumn_exit_td)

    out['entry_signal'] = (spring_entry | autumn_entry).astype(float)
    out['exit_signal'] = (spring_exit | autumn_exit).astype(float)
    out['window_id'] = 0.0
    out.loc[spring_entry | spring_exit, 'window_id'] = 1.0
    out.loc[autumn_entry | autumn_exit, 'window_id'] = 2.0

    cols = [
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'month', 'trading_day', 'entry_signal', 'exit_signal', 'window_id'
    ]
    return out[cols].dropna(subset=['open', 'high', 'low', 'close'])


class GoldSeasonalWindowsFeed(bt.feeds.PandasData):
    lines = ('month', 'trading_day', 'entry_signal', 'exit_signal', 'window_id')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month', 6), ('trading_day', 7), ('entry_signal', 8), ('exit_signal', 9), ('window_id', 10),
    )


class GoldSeasonalWindowsStrategy(bt.Strategy):
    params = dict(
        leverage=1.5,
        spring_entry_month=3,
        spring_entry_td=10,
        spring_exit_month=6,
        spring_exit_td=2,
        autumn_entry_month=10,
        autumn_entry_td=12,
        autumn_exit_month=11,
        autumn_exit_td=19,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.broker_value_series = []

    def _get_target_size(self, target_notional_pct, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) / (execution_price * multiplier)
        return max(0.01, round(size, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        entry_signal = float(self.data.entry_signal[0]) > 0.5
        exit_signal = float(self.data.exit_signal[0]) > 0.5
        if not self.position:
            if entry_signal:
                self.buy_count += 1
                target_size = self._get_target_size(float(self.p.leverage))
                self.pending_order = self.buy(size=target_size)
            return
        if exit_signal:
            self.sell_count += 1
            self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
