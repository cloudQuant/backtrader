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


def prepare_kelly_data(frame):
    return frame[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()


class KellyOptimalFStrategy(bt.Strategy):
    params = dict(
        method='kelly',
        lookback=126,
        trend_period=63,
        kelly_adjustment=0.5,
        max_fraction=0.20,
        optimal_f_adjustment=0.5,
        optimal_f_step=0.02,
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
        self.position_fraction_series = []

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

    def _kelly_fraction(self, returns):
        mean_return = float(np.mean(returns))
        variance = float(np.var(returns))
        if variance <= 0:
            return 0.0
        fraction = mean_return / variance
        fraction = max(0.0, fraction) * float(self.p.kelly_adjustment)
        return min(fraction, float(self.p.max_fraction))

    def _optimal_f(self, returns):
        best_f = 0.0
        best_score = -1e18
        for f_value in np.arange(0.0, 1.0 + float(self.p.optimal_f_step), float(self.p.optimal_f_step)):
            wealth_path = 1.0 + f_value * returns
            if np.any(wealth_path <= 0):
                continue
            score = float(np.prod(wealth_path))
            if score > best_score:
                best_score = score
                best_f = float(f_value)
        return min(best_f * float(self.p.optimal_f_adjustment), float(self.p.max_fraction))

    def next(self):
        self.bar_num += 1
        data = self.datas[0]
        self.broker_value_series.append((bt.num2date(data.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        lookback = int(self.p.lookback)
        trend_period = int(self.p.trend_period)
        if len(data) <= max(lookback, trend_period):
            return
        closes = np.array([float(data.close[-i]) for i in range(lookback - 1, -1, -1)], dtype=float)
        returns = pd.Series(closes).pct_change().dropna().to_numpy()
        trend_return = float(data.close[0] / data.close[-trend_period] - 1.0)
        if str(self.p.method).lower() == 'optimal_f':
            fraction = self._optimal_f(returns)
        else:
            fraction = self._kelly_fraction(returns)
        if trend_return <= 0:
            fraction = 0.0
        self.position_fraction_series.append(fraction)
        current_pos = float(self.getposition(data).size)
        target_size = self._target_size(data, fraction)
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
