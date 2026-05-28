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


def prepare_trend_mean_reversion_data(frame):
    return frame[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()


class BitcoinTrendMeanReversionStrategy(bt.Strategy):
    params = dict(
        short_term=5,
        medium_term=60,
        long_term=120,
        sma_period=50,
        momentum_period=20,
        rsi_period=14,
        rsi_oversold=30,
        rsi_overbought=70,
        zscore_period=20,
        zscore_threshold=2.0,
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
        self.trend_days = 0
        self.mean_reversion_days = 0

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

    def _rsi(self, values, period):
        series = pd.Series(values)
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return float((100 - (100 / (1 + rs))).iloc[-1]) if not rs.empty else 50.0

    def _zscore(self, values, period):
        series = pd.Series(values)
        window = series.iloc[-period:]
        std = float(window.std())
        if std == 0:
            return 0.0
        return float((window.iloc[-1] - window.mean()) / std)

    def next(self):
        self.bar_num += 1
        data = self.datas[0]
        self.broker_value_series.append((bt.num2date(data.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        required = max(int(self.p.long_term), int(self.p.sma_period), int(self.p.zscore_period), int(self.p.rsi_period))
        if len(data) <= required:
            return
        closes = [float(data.close[-i]) for i in range(required - 1, -1, -1)]
        short_return = float(data.close[0] / data.close[-int(self.p.short_term)] - 1.0)
        medium_return = float(data.close[0] / data.close[-int(self.p.medium_term)] - 1.0)
        long_return = float(data.close[0] / data.close[-int(self.p.long_term)] - 1.0)
        sma = float(np.mean(closes[-int(self.p.sma_period):]))
        rsi_value = self._rsi(closes, int(self.p.rsi_period))
        zscore = self._zscore(closes, int(self.p.zscore_period))
        if long_return > 0 and medium_return > 0:
            signal = 1.0 if float(data.close[0]) > sma else 0.0
            self.trend_days += 1
        else:
            if short_return < 0 and rsi_value < float(self.p.rsi_oversold) and zscore < -float(self.p.zscore_threshold):
                signal = 1.0
            elif short_return > 0 and rsi_value > float(self.p.rsi_overbought) and zscore > float(self.p.zscore_threshold):
                signal = 0.0
            else:
                signal = 0.0 if long_return < 0 else float(self.getposition(data).size > 0)
            self.mean_reversion_days += 1
        target_pct = float(self.p.position_size) * signal
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
