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


def prepare_stiffness_features(df, params):
    """准备刚度指标策略特征"""
    out = df.copy()
    ma_period = int(params.get('ma_period', 100))
    lookback = int(params.get('lookback', 60))
    std_coeff = float(params.get('std_coeff', 0.2))
    entry_threshold = float(params.get('entry_threshold', 95))
    exit_threshold = float(params.get('exit_threshold', 50))
    
    # 计算移动平均线
    out['ma'] = out['close'].rolling(window=ma_period).mean()
    
    # 计算标准差
    out['std'] = out['close'].rolling(window=ma_period).std()
    
    # 计算波动率带：MA - 0.2 * Std
    out['stiffness_band'] = out['ma'] - std_coeff * out['std']
    
    # 统计过去lookback日内价格高于波动率带的天数
    out['above_band'] = (out['close'] > out['stiffness_band']).astype(float)
    out['percent_above'] = out['above_band'].rolling(window=lookback).sum() / lookback * 100
    
    # 使用3日EMA平滑
    out['stiffness'] = out['percent_above'].ewm(span=3).mean()
    
    # 入场信号：Stiffness向上穿越entry_threshold
    out['entry_signal'] = ((out['stiffness'] > entry_threshold) & 
                           (out['stiffness'].shift(1) <= entry_threshold)).astype(float)
    
    # 出场信号：Stiffness向下穿越exit_threshold
    out['exit_signal'] = ((out['stiffness'] < exit_threshold) & 
                          (out['stiffness'].shift(1) >= exit_threshold)).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'stiffness', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5StiffnessFeed(bt.feeds.PandasData):
    lines = ('stiffness', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('stiffness', 6), ('entry_signal', 7), ('exit_signal', 8),
    )


class StiffnessTrendStrategy(bt.Strategy):
    params = dict(
        ma_period=100,
        lookback=60,
        std_coeff=0.2,
        entry_threshold=95,
        exit_threshold=50,
        max_holding=84,
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
        exit_signal = float(self.data.exit_signal[0]) > 0.5
        
        # 无持仓时检查入场
        if not self.position:
            if entry_signal:
                self.buy_count += 1
                self.entry_bar = self.bar_num
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
            return
        
        # 有持仓时检查出场
        if exit_signal:
            self.sell_count += 1
            self.pending_order = self.close()
            return
        
        # 最大持有天数出场
        holding_days = self.bar_num - self.entry_bar
        if holding_days >= self.p.max_holding:
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
