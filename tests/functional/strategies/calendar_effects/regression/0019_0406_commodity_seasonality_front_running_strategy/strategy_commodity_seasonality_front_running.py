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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


def _calc_front_run_months(strong_months, months_before):
    front_run_months = []
    for month in strong_months:
        front_run = month - months_before
        if front_run <= 0:
            front_run += 12
        front_run_months.append(front_run)
    return sorted(set(front_run_months))


def prepare_front_running_features(price_df, params):
    out = price_df.copy()
    strong_months = [int(v) for v in params.get('strong_months', [1, 2, 9, 10, 11, 12])]
    weak_months = [int(v) for v in params.get('weak_months', [3, 7, 8])]
    months_before = int(params.get('front_run_months_before', 1))
    front_run_target = float(params.get('front_run_target_percent', 0.75))
    strong_target = float(params.get('strong_target_percent', 1.0))
    front_run_months = _calc_front_run_months(strong_months, months_before)

    out['month'] = pd.Series(out.index.month, index=out.index, dtype='float64')
    out['is_front_run_month'] = pd.Series([1.0 if idx.month in front_run_months else 0.0 for idx in out.index], index=out.index)
    out['is_strong_month'] = pd.Series([1.0 if idx.month in strong_months else 0.0 for idx in out.index], index=out.index)
    out['is_weak_month'] = pd.Series([1.0 if idx.month in weak_months else 0.0 for idx in out.index], index=out.index)
    out['target_percent'] = 0.0
    out.loc[out['is_strong_month'] > 0.5, 'target_percent'] = strong_target
    out.loc[(out['is_front_run_month'] > 0.5) & (out['is_strong_month'] <= 0.5), 'target_percent'] = front_run_target
    out['in_trade_window'] = (out['target_percent'] > 0).astype(float)
    prev_window = out['in_trade_window'].shift(1).fillna(0.0)
    out['entry_signal'] = ((out['in_trade_window'] > 0.5) & (prev_window <= 0.5)).astype(float)
    out['exit_signal'] = ((out['in_trade_window'] <= 0.5) & (prev_window > 0.5)).astype(float)
    return out[[
        'open', 'high', 'low', 'close', 'volume', 'openinterest',
        'month', 'is_front_run_month', 'is_strong_month', 'is_weak_month',
        'target_percent', 'in_trade_window', 'entry_signal', 'exit_signal',
    ]].copy()


class CommoditySeasonalityFrontRunFeed(bt.feeds.PandasData):
    lines = ('month', 'is_front_run_month', 'is_strong_month', 'is_weak_month', 'target_percent', 'in_trade_window', 'entry_signal', 'exit_signal')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month', 6), ('is_front_run_month', 7), ('is_strong_month', 8), ('is_weak_month', 9), ('target_percent', 10), ('in_trade_window', 11), ('entry_signal', 12), ('exit_signal', 13),
    )


class CommoditySeasonalityFrontRunningStrategy(bt.Strategy):
    params = dict(
        stop_loss_pct=0.03,
        strong_months=[1, 2, 9, 10, 11, 12],
        weak_months=[3, 7, 8],
        front_run_months_before=1,
        front_run_target_percent=0.75,
        strong_target_percent=1.0,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.entry_price = None
        self.stop_price = None
        self.broker_value_series = []
        self.front_run_days = 0
        self.strong_days = 0
        self.weak_days = 0

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if float(self.data.is_front_run_month[0]) > 0.5:
            self.front_run_days += 1
        if float(self.data.is_strong_month[0]) > 0.5:
            self.strong_days += 1
        if float(self.data.is_weak_month[0]) > 0.5:
            self.weak_days += 1
        if self.pending_order is not None:
            return
        close = float(self.data.close[0])
        low = float(self.data.low[0])
        if self.position:
            if self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if float(self.data.exit_signal[0]) > 0.5 or float(self.data.target_percent[0]) <= 0:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            target_pct = max(0.0, min(1.0, float(self.data.target_percent[0])))
            self.pending_order = self.order_target_percent(target=target_pct)
            return
        if float(self.data.entry_signal[0]) > 0.5 and float(self.data.target_percent[0]) > 0:
            self.buy_count += 1
            self.pending_order = self.order_target_percent(target=float(self.data.target_percent[0]))
            self.entry_price = close
            self.stop_price = close * (1.0 - float(self.p.stop_loss_pct))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
