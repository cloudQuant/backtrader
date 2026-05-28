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


def prepare_seasonal_inputs(frame, params):
    prepared = frame[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    prepared['intraday_return'] = prepared['close'] / prepared['open'] - 1.0
    prepared['overnight_return'] = prepared['open'] / prepared['close'].shift(1) - 1.0
    prepared['weekday'] = prepared.index.dayofweek
    lookback = int(params.get('lookback_days', 63))
    min_samples = int(params.get('min_samples', 5))
    top_n = int(params.get('target_weekdays_count', 2))
    use_overnight = bool(params.get('use_overnight', True))
    signal_lookup = {}
    for idx in range(lookback, len(prepared)):
        date = pd.Timestamp(prepared.index[idx]).tz_localize(None)
        window = prepared.iloc[idx - lookback:idx].copy()
        metric = 'overnight_return' if use_overnight else 'intraday_return'
        grouped = window.groupby('weekday')[metric].agg(['mean', 'count']).reset_index()
        grouped = grouped[grouped['count'] >= min_samples].sort_values('mean', ascending=False)
        if grouped.empty:
            continue
        target_weekdays = grouped.head(top_n)['weekday'].astype(int).tolist()
        signal_lookup[date] = target_weekdays
    prepared = prepared.dropna().copy()
    return prepared, signal_lookup


class BitcoinSeasonalAnomaliesStrategy(bt.Strategy):
    params = dict(
        position_size=1.0,
        signal_lookup=None,
        lookback_days=63,
        min_samples=5,
        target_weekdays_count=2,
        use_overnight=True,
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
        current_dt = pd.Timestamp(bt.num2date(data.datetime[0])).tz_localize(None)
        self.broker_value_series.append((bt.num2date(data.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        target_weekdays = (self.p.signal_lookup or {}).get(current_dt)
        if not target_weekdays:
            return
        weekday = bt.num2date(data.datetime[0]).weekday()
        if weekday in target_weekdays:
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
