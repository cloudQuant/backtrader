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



def prepare_cppi_portfolio_insurance_features(df, params):
    floor_pct = float(params.get('floor_pct', 0.8))
    cppi_mult = float(params.get('multiplier', 3.0))
    rebalance_days = int(params.get('rebalance_days', 21))

    out = df.copy()
    # Running max as proxy for portfolio high
    running_max = out['close'].cummax()
    floor_value = running_max * floor_pct
    out['cushion_pct'] = (out['close'] - floor_value) / out['close'].replace(0, np.inf)
    out['exposure'] = (out['cushion_pct'] * cppi_mult).clip(0.0, 1.0)

    out['rebalance_flag'] = 0.0
    cnt = 0
    for i in range(len(out)):
        cnt += 1
        if cnt >= rebalance_days:
            out.iloc[i, out.columns.get_loc('rebalance_flag')] = 1.0
            cnt = 0

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest',
               'cushion_pct', 'exposure', 'rebalance_flag']].copy()
    return out.dropna()


class Mt5CppiPortfolioInsuranceFeed(bt.feeds.PandasData):
    lines = ('cushion_pct', 'exposure', 'rebalance_flag',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('cushion_pct', 6),
        ('exposure', 7),
        ('rebalance_flag', 8),
    )


class CppiPortfolioInsuranceStrategy(bt.Strategy):
    params = dict(
        floor_pct=0.8,
        multiplier=3.0,
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
        exposure = float(self.data.exposure[0])
        if not self.position:
            if exposure > 0.1:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=exposure))
        else:
            if exposure < 0.05:
                self.sell_count += 1
                self.pending_order = self.close()
            else:
                current_size = abs(self.position.size)
                target_size = self._get_position_size(target_notional_pct=exposure)
                if abs(current_size - target_size) > target_size * 0.2:
                    self.sell_count += 1
                    self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        pass

