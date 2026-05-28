from __future__ import absolute_import, division, print_function, unicode_literals

import io
import backtrader as bt
import pandas as pd
import numpy as np


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
    df = df.set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df



def prepare_taa_aggregate_timing_features(df, params):
    ma_fast = int(params.get('ma_fast', 50))
    ma_slow = int(params.get('ma_slow', 200))
    mom_period = int(params.get('mom_period', 120))
    rebalance_days = int(params.get('rebalance_days', 21))

    out = df.copy()
    fast_ma = out['close'].rolling(ma_fast).mean()
    slow_ma = out['close'].rolling(ma_slow).mean()
    out['ma_signal'] = (fast_ma > slow_ma).astype(float)
    out['mom_signal'] = (out['close'].pct_change(mom_period) > 0).astype(float)
    out['composite'] = (out['ma_signal'] + out['mom_signal']) / 2.0

    out['rebalance_flag'] = 0.0
    cnt = 0
    for i in range(len(out)):
        cnt += 1
        if cnt >= rebalance_days:
            out.iloc[i, out.columns.get_loc('rebalance_flag')] = 1.0
            cnt = 0

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest',
               'ma_signal', 'mom_signal', 'composite', 'rebalance_flag']].copy()
    return out.dropna()


class Mt5TaaAggregateTimingFeed(bt.feeds.PandasData):
    lines = ('ma_signal', 'mom_signal', 'composite', 'rebalance_flag',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('ma_signal', 6),
        ('mom_signal', 7),
        ('composite', 8),
        ('rebalance_flag', 9),
    )


class TaaAggregateTimingStrategy(bt.Strategy):
    params = dict(
        ma_fast=50,
        ma_slow=200,
        mom_period=120,
        rebalance_days=21,
        lot_size=1.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_bar = 0
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
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
        rebalance = float(self.data.rebalance_flag[0]) > 0.5
        if not rebalance:
            return
        composite = float(self.data.composite[0])
        if not self.position:
            if composite > 0.5:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size())
        else:
            if composite < 0.5:
                self.sell_count += 1
                self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        pass

