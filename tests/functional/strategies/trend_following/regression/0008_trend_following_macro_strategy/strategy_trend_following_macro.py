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


def prepare_macro_inputs(asset_map):
    aligned_index = None
    prepared = {}
    for symbol, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    return prepared, aligned_index


class TrendFollowingMacroStrategy(bt.Strategy):
    params = dict(
        sma_period=200,
        momentum_period=252,
        inflation_period=126,
        rate_sma_period=252,
        market_weight=0.7,
        macro_weight=0.3,
        long_threshold=0.3,
        short_threshold=-0.3,
        position_size=1.0,
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

    def _sma(self, data, period):
        values = [float(data.close[-i]) for i in range(period)]
        return sum(values) / len(values)

    def _signal(self):
        trade_asset = self.datas[0]
        market = self.datas[1]
        inflation = self.datas[2]
        rate = self.datas[3]
        required = max(int(self.p.sma_period), int(self.p.momentum_period), int(self.p.inflation_period), int(self.p.rate_sma_period))
        if len(trade_asset) <= required:
            return None
        sma_signal = 1.0 if float(trade_asset.close[0]) > self._sma(trade_asset, int(self.p.sma_period)) else -1.0
        momentum_signal = 1.0 if float(market.close[0] / market.close[-int(self.p.momentum_period)] - 1.0) > 0 else -1.0
        market_signal = (sma_signal + momentum_signal) / 2.0
        inflation_signal = 1.0 if float(inflation.close[0] / inflation.close[-int(self.p.inflation_period)] - 1.0) > 0 else -1.0
        rate_signal = 1.0 if float(rate.close[0]) > self._sma(rate, int(self.p.rate_sma_period)) else -1.0
        macro_signal = (inflation_signal + rate_signal) / 2.0
        combined_signal = float(self.p.market_weight) * market_signal + float(self.p.macro_weight) * macro_signal
        return combined_signal, market_signal, macro_signal

    def next(self):
        self.bar_num += 1
        data = self.datas[0]
        self.broker_value_series.append((bt.num2date(data.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        signal = self._signal()
        if signal is None:
            return
        combined_signal, _, _ = signal
        if combined_signal > float(self.p.long_threshold):
            target_pct = float(self.p.position_size)
            self.long_days += 1
        elif combined_signal < float(self.p.short_threshold):
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
