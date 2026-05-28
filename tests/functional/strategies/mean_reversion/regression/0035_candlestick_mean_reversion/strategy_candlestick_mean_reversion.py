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


def calculate_rsi(close, period=2):
    """计算RSI指标"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.inf)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def detect_hammer(open_price, high, low, close):
    """检测锤子线形态"""
    body = abs(close - open_price)
    lower_shadow = pd.concat([open_price, close], axis=1).min(axis=1) - low
    upper_shadow = high - pd.concat([open_price, close], axis=1).max(axis=1)
    total_range = high - low
    
    # 锤子线：实体小，下影线长（至少是实体的2倍），上影线短
    is_hammer = (
        (total_range > 0) &
        (body > 0) &
        (lower_shadow >= 2 * body) &
        (upper_shadow <= body * 0.5)
    )
    return is_hammer.astype(float)


def detect_bullish_engulfing(open_price, close):
    """检测看涨吞没形态"""
    prev_open = open_price.shift(1)
    prev_close = close.shift(1)
    
    # 看涨吞没：前一根阴线，当前阳线完全吞没前一根
    is_engulfing = (
        (prev_close < prev_open) &  # 前一根阴线
        (close > open_price) &  # 当前阳线
        (close > prev_open) &  # 当前收盘高于前一根开盘
        (open_price < prev_close)  # 当前开盘低于前一根收盘
    )
    return is_engulfing.astype(float)


def prepare_candlestick_mean_reversion_features(df, params):
    """准备K线形态均值回归策略特征"""
    out = df.copy()
    rsi_period = int(params.get('rsi_period', 2))
    rsi_oversold = float(params.get('rsi_oversold', 5))
    
    # 计算RSI
    out['rsi'] = calculate_rsi(out['close'], rsi_period)
    
    # 检测K线形态
    out['hammer'] = detect_hammer(out['open'], out['high'], out['low'], out['close'])
    out['bullish_engulfing'] = detect_bullish_engulfing(out['open'], out['close'])
    
    # 入场信号：RSI超卖 + 看涨K线形态
    out['entry_signal'] = (
        (out['rsi'] < rsi_oversold) & 
        ((out['hammer'] > 0.5) | (out['bullish_engulfing'] > 0.5))
    ).astype(float)
    
    # 出场信号：持有N天后
    out['exit_signal'] = 0.0
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'rsi', 'hammer', 'bullish_engulfing', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5CandlestickMeanReversionFeed(bt.feeds.PandasData):
    lines = ('rsi', 'hammer', 'bullish_engulfing', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('rsi', 6), ('hammer', 7), ('bullish_engulfing', 8),
        ('entry_signal', 9), ('exit_signal', 10),
    )


class CandlestickMeanReversionStrategy(bt.Strategy):
    params = dict(
        rsi_period=2,
        rsi_oversold=5,
        rsi_overbought=70,
        holding_days=5,
        lot_size=1.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
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
        
        # 无持仓时检查入场
        if not self.position:
            if entry_signal:
                self.buy_count += 1
                self.entry_bar = self.bar_num
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
            return
        
        # 有持仓时检查出场：固定持有天数
        holding_days = self.bar_num - self.entry_bar
        if holding_days >= self.p.holding_days:
            self.sell_count += 1
            self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
