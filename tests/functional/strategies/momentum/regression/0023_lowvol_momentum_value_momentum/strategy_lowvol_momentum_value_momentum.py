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



def prepare_lowvol_momentum_value_momentum_features(df, params):
    vol_lookback = int(params.get('vol_lookback', 60))
    mom_lookback = int(params.get('mom_lookback', 120))
    rebalance_days = int(params.get('rebalance_days', 63))

    out = df.copy()
    ret = out['close'].pct_change()
    # Rolling volatility rank (low vol = high rank)
    vol = ret.rolling(vol_lookback).std() * np.sqrt(252)
    out['vol_rank'] = vol.rolling(min(252, len(vol))).rank(pct=True)
    out['vol_rank'] = 1.0 - out['vol_rank']  # Invert: low vol = high score

    # Momentum rank
    mom = out['close'].pct_change(mom_lookback)
    out['mom_rank'] = mom.rolling(min(252, len(mom))).rank(pct=True)

    # Composite score
    out['composite_score'] = (out['vol_rank'] + out['mom_rank']) / 2.0

    # Rebalance flag
    out['rebalance_flag'] = 0.0
    cnt = 0
    for i in range(len(out)):
        cnt += 1
        if cnt >= rebalance_days:
            out.iloc[i, out.columns.get_loc('rebalance_flag')] = 1.0
            cnt = 0

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest',
               'vol_rank', 'mom_rank', 'composite_score', 'rebalance_flag']].copy()
    return out.dropna()


class Mt5LowvolMomentumValueMomentumFeed(bt.feeds.PandasData):
    lines = ('vol_rank', 'mom_rank', 'composite_score', 'rebalance_flag',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('vol_rank', 6),
        ('mom_rank', 7),
        ('composite_score', 8),
        ('rebalance_flag', 9),
    )


class LowvolMomentumValueMomentumStrategy(bt.Strategy):
    params = dict(
        vol_lookback=60,
        mom_lookback=120,
        rebalance_days=63,
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
        score = float(self.data.composite_score[0])

        if not rebalance:
            return

        if not self.position:
            if score > 0.6:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size())
        else:
            if score < 0.4:
                self.sell_count += 1
                self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        pass

