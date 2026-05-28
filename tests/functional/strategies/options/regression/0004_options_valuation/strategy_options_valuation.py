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



def prepare_options_valuation_features(df, params):
    hv_period = int(params.get('hv_period', 20))
    iv_lookback = int(params.get('iv_lookback', 252))
    iv_rank_low = float(params.get('iv_rank_low', 0.2))
    iv_rank_high = float(params.get('iv_rank_high', 0.8))

    out = df.copy()
    ret = out['close'].pct_change()
    out['hist_vol'] = ret.rolling(hv_period).std() * np.sqrt(252)

    # Use realized vol as proxy for IV rank
    out['iv_rank'] = out['hist_vol'].rolling(min(iv_lookback, len(out))).rank(pct=True)

    # Buy when vol cheap (low IV rank), sell when vol expensive (high IV rank)
    out['signal'] = 0.0
    out.loc[out['iv_rank'] < iv_rank_low, 'signal'] = 1.0
    out.loc[out['iv_rank'] > iv_rank_high, 'signal'] = -1.0

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest',
               'hist_vol', 'iv_rank', 'signal']].copy()
    return out.dropna()


class Mt5OptionsValuationFeed(bt.feeds.PandasData):
    lines = ('hist_vol', 'iv_rank', 'signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('hist_vol', 6),
        ('iv_rank', 7),
        ('signal', 8),
    )


class OptionsValuationStrategy(bt.Strategy):
    params = dict(
        hv_period=20,
        iv_lookback=252,
        iv_rank_low=0.2,
        iv_rank_high=0.8,
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

        signal = float(self.data.signal[0])

        if not self.position:
            if signal > 0.5:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size())
        else:
            if signal < -0.5:
                self.sell_count += 1
                self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        pass

