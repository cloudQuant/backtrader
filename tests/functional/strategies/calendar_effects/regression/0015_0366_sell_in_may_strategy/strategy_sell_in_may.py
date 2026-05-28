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


def prepare_sell_in_may_data(frame, params):
    prepared = frame[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    high = prepared['high']
    low = prepared['low']
    close = prepared['close']
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    prepared['atr'] = tr.rolling(int(params.get('atr_period', 14))).mean()
    typical_price = (prepared['high'] + prepared['low'] + prepared['close']) / 3.0
    price_change = np.log(typical_price).diff()
    vinter = price_change.rolling(30).std()
    cutoff = float(params.get('vfi_coef', 0.2)) * vinter * prepared['close']
    volume = prepared['volume'].replace(0, np.nan).ffill().fillna(1.0)
    vc = np.minimum(volume, volume.rolling(int(params.get('vfi_period', 130))).mean() * float(params.get('vfi_vcoef', 2.5)))
    mf = typical_price - typical_price.shift(1)
    vcp = np.where(mf > cutoff, vc, np.where(mf < -cutoff, -vc, 0.0))
    prepared['vfi'] = pd.Series(vcp, index=prepared.index).rolling(int(params.get('vfi_period', 130))).sum() / volume.rolling(int(params.get('vfi_period', 130))).mean()
    prepared['vfi'] = prepared['vfi'].ewm(span=3, adjust=False).mean()
    prepared = prepared.dropna().copy()
    return prepared


class SellInMayFeed(bt.feeds.PandasData):
    lines = ('atr', 'vfi')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('atr', 6), ('vfi', 7),
    )


class SellInMayStrategy(bt.Strategy):
    params = dict(
        sell_month=8,
        buy_month=10,
        atr_threshold_pct=0.06,
        vfi_threshold=-20.0,
        position_size=1.0,
        atr_period=14,
        vfi_period=130,
        vfi_coef=0.2,
        vfi_vcoef=2.5,
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
        self.in_market_days = 0
        self.out_market_days = 0

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
        current_month = bt.num2date(data.datetime[0]).month
        buy_seasonal = current_month >= int(self.p.buy_month) or current_month < int(self.p.sell_month)
        sell_seasonal = current_month == int(self.p.sell_month)
        atr_pct = float(data.atr[0] / data.close[0]) if float(data.close[0]) != 0 else 0.0
        vol_condition = atr_pct < float(self.p.atr_threshold_pct)
        vfi_condition = float(data.vfi[0]) > float(self.p.vfi_threshold)
        target_pct = 0.0
        if sell_seasonal:
            target_pct = 0.0
            self.out_market_days += 1
        elif buy_seasonal and vol_condition and vfi_condition:
            target_pct = float(self.p.position_size)
            self.in_market_days += 1
        else:
            target_pct = 0.0
            self.out_market_days += 1
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
