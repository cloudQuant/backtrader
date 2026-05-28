from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
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


def prepare_lrema_data(frame, params):
    prepared = frame[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    ema_period = int(params.get('ema_period', 30))
    reg_period = int(params.get('reg_period', 20))
    deviation_multiplier = float(params.get('deviation_multiplier', 1.0))
    x = np.arange(reg_period)
    reg_values = []
    slopes = []
    closes = prepared['close'].astype(float).to_numpy()
    for idx in range(len(prepared)):
        if idx + 1 < reg_period:
            reg_values.append(np.nan)
            slopes.append(np.nan)
            continue
        window = closes[idx - reg_period + 1: idx + 1]
        slope, intercept = np.polyfit(x, window, 1)
        reg_value = intercept + slope * (reg_period - 1)
        reg_values.append(reg_value)
        slopes.append(slope)
    prepared['regression'] = reg_values
    prepared['slope'] = slopes
    prepared['adjusted_price'] = prepared['close'] + deviation_multiplier * (prepared['close'] - prepared['regression'])
    prepared['lrema'] = prepared['adjusted_price'].ewm(span=ema_period, adjust=False).mean()
    prepared = prepared.dropna().copy()
    return prepared


class LREMAFeed(bt.feeds.PandasData):
    lines = ('regression', 'slope', 'adjusted_price', 'lrema')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('regression', 6), ('slope', 7), ('adjusted_price', 8), ('lrema', 9),
    )


class LREMAStrategy(bt.Strategy):
    params = dict(
        position_size=1.0,
        ema_period=30,
        reg_period=20,
        deviation_multiplier=1.0,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.broker_value_series = []
        self.long_days = 0
        self.short_days = 0
        self.flat_days = 0

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _target_size(self, data, target_pct):
        broker_value = float(self.broker.getvalue())
        price = float(data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * abs(float(target_pct)) / (price * multiplier)
        size = max(0.01, round(size, 2))
        return size if target_pct >= 0 else -size

    def next(self):
        self.bar_num += 1
        data = self.datas[0]
        self.broker_value_series.append((bt.num2date(data.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        price = float(data.close[0])
        lrema = float(data.lrema[0])
        slope = float(data.slope[0])
        if price > lrema and slope > 0:
            target_pct = float(self.p.position_size)
            self.long_days += 1
        elif price < lrema and slope < 0:
            target_pct = -float(self.p.position_size)
            self.short_days += 1
        else:
            target_pct = 0.0
            self.flat_days += 1
        current_pos = float(self.getposition(data).size)
        target_size = self._target_size(data, target_pct)
        if abs(target_size - current_pos) < 0.01:
            return
        if target_size > current_pos:
            self.buy_count += 1
        elif target_size < current_pos:
            self.sell_count += 1
        self._submit(self.order_target_size(data=data, target=target_size))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
