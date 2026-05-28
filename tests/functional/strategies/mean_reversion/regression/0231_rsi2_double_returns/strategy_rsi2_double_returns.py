from __future__ import absolute_import, division, print_function, unicode_literals

import io
from datetime import timedelta

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    frame = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = frame['<DATE>'].astype(str) + ' ' + frame['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    frame['datetime'] = parsed
    frame = frame.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    frame['openinterest'] = 0
    frame['volume'] = frame['tick_volume'] if 'tick_volume' in frame.columns else 0
    frame = frame[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    frame = frame.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        frame = frame[frame.index >= fromdate]
    if todate is not None:
        frame = frame[frame.index <= todate]
    return frame


class RSI2DoubleReturnsStrategy(bt.Strategy):
    params = dict(
        rsi_period=2,
        rsi_threshold=10,
        ma_period=100,
        atr_period=14,
        volatility_period=100,
        high_vol_threshold=0.25,
        medium_vol_threshold=0.15,
        high_vol_entry_atr_multiple=0.75,
        medium_vol_entry_atr_multiple=0.5,
        low_vol_entry_atr_multiple=0.25,
        max_holding_days=10,
        exit_rsi=50,
        stop_atr_multiple=2.0,
        target_percent=0.95,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.sma = bt.indicators.SimpleMovingAverage(self.data0.close, period=self.p.ma_period)
        self.rsi = bt.indicators.RSI_SMA(self.data0.close, period=self.p.rsi_period, safediv=True)
        self.atr = bt.indicators.ATR(self.data0, period=self.p.atr_period)
        self.daily_returns = bt.indicators.PercentChange(self.data0.close, period=1)
        self.volatility = bt.indicators.StandardDeviation(self.daily_returns, period=self.p.volatility_period) * np.sqrt(252)
        self.pending_entry = None
        self.pending_exit = None
        self.entry_bar = None
        self.entry_price_value = None
        self.current_stop = None
        self.bar_num = 0
        self.rebalance_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.broker_value_series = []

    def _calc_entry_offset(self):
        current_vol = float(self.volatility[0]) if len(self) > self.p.volatility_period else np.nan
        atr_value = float(self.atr[0]) if len(self) > self.p.atr_period else np.nan
        if np.isnan(atr_value) or atr_value <= 0:
            return 0.0
        if np.isnan(current_vol):
            return self.p.medium_vol_entry_atr_multiple * atr_value
        if current_vol > self.p.high_vol_threshold:
            return self.p.high_vol_entry_atr_multiple * atr_value
        if current_vol > self.p.medium_vol_threshold:
            return self.p.medium_vol_entry_atr_multiple * atr_value
        return self.p.low_vol_entry_atr_multiple * atr_value

    def _place_entry_order(self):
        entry_offset = self._calc_entry_offset()
        limit_price = max(float(self.data0.close[0]) - entry_offset, 0.0)
        portfolio_value = float(self.broker.getvalue())
        target_value = portfolio_value * float(self.p.target_percent)
        size = int(target_value / limit_price) if limit_price > 0 else 0
        if size <= 0:
            return
        valid_until = bt.date2num(self.data.datetime.datetime(0) + timedelta(days=1))
        self.pending_entry = self.buy(data=self.data0, size=size, exectype=bt.Order.Limit, price=limit_price, valid=valid_until)
        self.rebalance_count += 1

    def _place_exit_order(self):
        self.pending_exit = self.close(data=self.data0)
        self.rebalance_count += 1

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if len(self) <= max(self.p.ma_period, self.p.volatility_period, self.p.atr_period):
            return
        if self.pending_exit is not None:
            return
        position = self.getposition(self.data0)
        if position.size > 0:
            held_bars = 0 if self.entry_bar is None else len(self) - self.entry_bar
            stop_hit = self.current_stop is not None and float(self.data0.close[0]) < self.current_stop
            if float(self.rsi[0]) > self.p.exit_rsi or held_bars >= self.p.max_holding_days or stop_hit:
                self._place_exit_order()
            return
        if self.pending_entry is not None:
            return
        trend_ok = float(self.data0.close[0]) > float(self.sma[0])
        setup_ok = trend_ok and float(self.rsi[0]) < self.p.rsi_threshold
        if setup_ok:
            self._place_entry_order()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.entry_bar = len(self)
                self.entry_price_value = float(order.executed.price)
                atr_value = float(self.atr[0]) if not np.isnan(float(self.atr[0])) else 0.0
                self.current_stop = self.entry_price_value - self.p.stop_atr_multiple * atr_value
            elif order.issell():
                self.entry_bar = None
                self.entry_price_value = None
                self.current_stop = None
        if self.pending_entry is not None and order.ref == self.pending_entry.ref:
            self.pending_entry = None
        if self.pending_exit is not None and order.ref == self.pending_exit.ref:
            self.pending_exit = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
