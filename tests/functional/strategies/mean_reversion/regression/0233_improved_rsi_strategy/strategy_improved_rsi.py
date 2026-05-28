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


def prepare_improved_rsi_data(frame):
    return frame[['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()


class ImprovedRSIStrategy(bt.Strategy):
    params = dict(
        base_window=14,
        min_window=10,
        max_window=20,
        vol_lookback=60,
        oversold=30,
        overbought=70,
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
        self.rsi_series = []

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

    def _ema_rsi(self, prices, window):
        series = pd.Series(prices)
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        alpha = 2.0 / (window + 1.0)
        avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
        avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty and pd.notna(rsi.iloc[-1]) else 50.0

    def _volume_weighted_rsi(self, prices, volumes, window):
        price_series = pd.Series(prices)
        volume_series = pd.Series(volumes).replace(0, np.nan).ffill().fillna(1.0)
        delta = price_series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        weighted_gain = gain * volume_series
        weighted_loss = loss * volume_series
        denom = volume_series.rolling(window).sum().replace(0, np.nan)
        avg_gain = weighted_gain.rolling(window).sum() / denom
        avg_loss = weighted_loss.rolling(window).sum() / denom
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty and pd.notna(rsi.iloc[-1]) else 50.0

    def _adaptive_window(self, prices):
        series = pd.Series(prices)
        returns = series.pct_change()
        volatility = returns.rolling(int(self.p.vol_lookback)).std()
        current_vol = float(volatility.iloc[-1]) if not volatility.empty and pd.notna(volatility.iloc[-1]) else 0.0
        hist = volatility.dropna()
        if hist.empty or float(hist.max() - hist.min()) == 0.0:
            return int(self.p.base_window)
        normalized = (current_vol - float(hist.min())) / float(hist.max() - hist.min())
        adaptive = float(self.p.max_window) - normalized * (float(self.p.max_window) - float(self.p.min_window))
        return int(max(float(self.p.min_window), min(float(self.p.max_window), adaptive)))

    def next(self):
        self.bar_num += 1
        data = self.datas[0]
        self.broker_value_series.append((bt.num2date(data.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        required = max(int(self.p.vol_lookback), int(self.p.max_window)) + 5
        if len(data) <= required:
            return
        closes = [float(data.close[-i]) for i in range(required - 1, -1, -1)]
        volumes = [float(data.volume[-i]) for i in range(required - 1, -1, -1)]
        window = self._adaptive_window(closes)
        ema_rsi = self._ema_rsi(closes, window)
        vol_rsi = self._volume_weighted_rsi(closes, volumes, window)
        improved_rsi = 0.5 * ema_rsi + 0.5 * vol_rsi
        self.rsi_series.append(improved_rsi)
        if improved_rsi < float(self.p.oversold):
            target_pct = float(self.p.position_size)
        elif improved_rsi > float(self.p.overbought):
            target_pct = 0.0
        else:
            target_pct = float(self.getposition(data).size > 0) * float(self.p.position_size)
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
