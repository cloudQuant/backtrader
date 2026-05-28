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



def prepare_consecutive_down_rebound_features(df, params):
    down_days = int(params.get('down_days', 3))
    vol_bb_period = int(params.get('volume_bb_period', 20))
    vol_bb_std = float(params.get('volume_bb_std', 2.0))

    out = df.copy()
    # Consecutive down days
    down = (out['close'] < out['close'].shift(1)).astype(float)
    consec_down = down.rolling(down_days).sum()
    out['consecutive_down'] = (consec_down >= down_days).astype(float)

    # Volume Bollinger Band
    vol_ma = out['volume'].rolling(vol_bb_period).mean()
    vol_std = out['volume'].rolling(vol_bb_period).std()
    vol_upper = vol_ma + vol_bb_std * vol_std
    out['volume_signal'] = (out['volume'] > vol_upper).astype(float)

    # Entry: consecutive down + high volume
    out['entry_signal'] = ((out['consecutive_down'] > 0.5) & (out['volume_signal'] > 0.5)).astype(float)

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest',
               'consecutive_down', 'volume_signal', 'entry_signal']].copy()
    return out.dropna()


class Mt5ConsecutiveDownReboundFeed(bt.feeds.PandasData):
    lines = ('consecutive_down', 'volume_signal', 'entry_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('consecutive_down', 6),
        ('volume_signal', 7),
        ('entry_signal', 8),
    )


class ConsecutiveDownReboundStrategy(bt.Strategy):
    params = dict(
        down_days=3,
        volume_bb_period=20,
        volume_bb_std=2.0,
        holding_days=63,
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

        entry_signal = float(self.data.entry_signal[0]) > 0.5

        if not self.position:
            if entry_signal:
                self.buy_count += 1
                self.entry_bar = self.bar_num
                self.pending_order = self.buy(size=self._get_position_size())
            return

        holding_days = self.bar_num - self.entry_bar
        if holding_days >= self.p.holding_days:
            self.sell_count += 1
            self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        pass

