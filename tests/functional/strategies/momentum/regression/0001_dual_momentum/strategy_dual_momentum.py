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


def prepare_dual_momentum_features(df, params):
    """准备双动量策略特征"""
    out = df.copy()
    lookback = int(params.get('lookback_period', 252))
    risk_free = float(params.get('risk_free_threshold', 0.0))
    
    # 计算动量（过去lookback天的收益率）
    out['momentum'] = out['close'] / out['close'].shift(lookback) - 1
    
    # 绝对动量信号：动量 > 无风险利率阈值
    out['abs_momentum'] = (out['momentum'] > risk_free).astype(float)
    
    # 月末调仓标记
    out['month_end'] = (out.index.to_period('M') != out.index.to_period('M').shift(1)).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'momentum', 'abs_momentum', 'month_end']].copy()
    return out.dropna()


class Mt5DualMomentumFeed(bt.feeds.PandasData):
    lines = ('momentum', 'abs_momentum', 'month_end',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('momentum', 6), ('abs_momentum', 7), ('month_end', 8),
    )


class DualMomentumStrategy(bt.Strategy):
    params = dict(
        lookback_period=252,
        risk_free_threshold=0.0,
        rebalance_freq='monthly',
        lot_size=1.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.rebalance_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.current_month = None
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
        
        # 月度调仓
        month_key = bt.num2date(self.data.datetime[0]).month
        if month_key == self.current_month:
            return
        self.current_month = month_key
        
        abs_momentum = float(self.data.abs_momentum[0])
        
        # 根据绝对动量调仓
        if abs_momentum > 0.5:
            # 动量为正，持有
            if not self.position:
                self.rebalance_count += 1
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
        else:
            # 动量为负，空仓
            if self.position:
                self.rebalance_count += 1
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
