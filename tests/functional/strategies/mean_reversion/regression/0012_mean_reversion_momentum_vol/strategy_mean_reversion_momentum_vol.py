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


def prepare_mean_reversion_momentum_vol_features(df, params):
    """准备均值回归动量波动率策略特征"""
    out = df.copy()
    short_period = int(params.get('short_period', 5))
    long_period = int(params.get('long_period', 20))
    threshold_days = int(params.get('threshold_days', 16))
    
    # 计算短期动量
    out['short_momentum'] = out['close'].pct_change(short_period)
    
    # 计算长期动量
    out['long_momentum'] = out['close'].pct_change(long_period)
    
    # 计算波动率
    out['volatility'] = out['close'].pct_change().rolling(window=long_period).std()
    
    # 根据Hurst指数理论：短期用动量，长期用均值回归
    # 简化实现：当短期动量与长期动量方向一致时使用动量策略
    # 当短期动量与长期动量方向相反时使用均值回归
    
    # 动量信号：短期和长期动量都为正
    out['momentum_signal'] = (
        (out['short_momentum'] > 0) & 
        (out['long_momentum'] > 0)
    ).astype(float)
    
    # 均值回归信号：短期动量为负且长期动量为正（回调买入）
    out['mean_reversion_signal'] = (
        (out['short_momentum'] < -out['volatility']) & 
        (out['long_momentum'] > 0)
    ).astype(float)
    
    # 综合入场信号
    out['entry_signal'] = out['mean_reversion_signal']
    
    # 出场信号：短期动量转正
    out['exit_signal'] = (out['short_momentum'] > out['volatility'] * 0.5).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'short_momentum', 'long_momentum', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5MeanReversionMomentumVolFeed(bt.feeds.PandasData):
    lines = ('short_momentum', 'long_momentum', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('short_momentum', 6), ('long_momentum', 7), ('entry_signal', 8), ('exit_signal', 9),
    )


class MeanReversionMomentumVolStrategy(bt.Strategy):
    params = dict(
        short_period=5,
        long_period=20,
        threshold_days=16,
        holding_days=10,
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
        holding_days = self.bar_num - self.entry_bar
        if exit_signal or holding_days >= self.p.holding_days:
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
