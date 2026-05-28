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


def prepare_gold_momentum_mean_reversion_features(df, params):
    """准备黄金动量均值回归策略特征"""
    out = df.copy()
    momentum_period = int(params.get('momentum_period', 40))
    mean_period = int(params.get('mean_period', 250))
    momentum_threshold = float(params.get('momentum_threshold', 0.02))
    deviation_threshold = float(params.get('deviation_threshold', 2.0))
    
    # 计算动量得分
    out['momentum'] = out['close'].pct_change(momentum_period)
    
    # 计算长期均值和标准差
    out['mean'] = out['close'].rolling(window=mean_period).mean()
    out['std'] = out['close'].rolling(window=mean_period).std()
    
    # 计算偏离度（Z-score）
    out['deviation'] = (out['close'] - out['mean']) / out['std']
    
    # 动量信号：动量得分超过阈值
    out['momentum_signal'] = (out['momentum'] > momentum_threshold).astype(float)
    
    # 均值回归信号：偏离度低于负阈值
    out['mean_reversion_signal'] = (out['deviation'] < -deviation_threshold).astype(float)
    
    # 组合入场信号：动量做多且未显著偏离均值
    out['entry_signal'] = (
        (out['momentum_signal'] > 0.5) & 
        (out['deviation'] < deviation_threshold * 0.5)
    ).astype(float)
    
    # 出场信号：动量转负或价格回归均值
    out['exit_signal'] = (
        (out['momentum'] < 0) | 
        (abs(out['deviation']) < 0.5)
    ).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'momentum', 'deviation', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5GoldMomentumMeanReversionFeed(bt.feeds.PandasData):
    lines = ('momentum', 'deviation', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('momentum', 6), ('deviation', 7), ('entry_signal', 8), ('exit_signal', 9),
    )


class GoldMomentumMeanReversionStrategy(bt.Strategy):
    params = dict(
        momentum_period=40,
        mean_period=250,
        momentum_threshold=0.02,
        deviation_threshold=2.0,
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
