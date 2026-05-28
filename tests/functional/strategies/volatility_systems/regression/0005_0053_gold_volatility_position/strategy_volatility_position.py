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


def calculate_volatility_percentile(returns, vol_window, rank_window):
    """计算波动率百分位"""
    # 计算历史波动率
    volatility = returns.rolling(vol_window).std() * np.sqrt(252)
    # 计算波动率百分位
    vol_percentile = volatility.rolling(rank_window).rank(pct=True)
    return vol_percentile


def prepare_volatility_features(df, params):
    """准备波动率仓位调整策略特征"""
    out = df.copy()
    vol_window = int(params.get('vol_window', 20))
    rank_window = int(params.get('rank_window', 252))
    high_vol_threshold = float(params.get('high_vol_threshold', 0.8))
    low_vol_threshold = float(params.get('low_vol_threshold', 0.2))
    
    # 计算收益率
    out['returns'] = out['close'].pct_change()
    
    # 计算波动率百分位
    out['vol_percentile'] = calculate_volatility_percentile(out['returns'], vol_window, rank_window)
    
    # 生成仓位信号
    # 高波动：仓位50%
    # 低波动：仓位100%
    # 正常波动：仓位75%
    out['position_size'] = 0.75  # 默认正常波动
    out.loc[out['vol_percentile'] > high_vol_threshold, 'position_size'] = 0.5
    out.loc[out['vol_percentile'] < low_vol_threshold, 'position_size'] = 1.0
    
    # 生成入场信号：低波动时买入
    out['entry_signal'] = (out['vol_percentile'] < low_vol_threshold).astype(float)
    
    # 生成出场信号：高波动时减仓
    out['exit_signal'] = (out['vol_percentile'] > high_vol_threshold).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'vol_percentile', 'position_size', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5VolatilityFeed(bt.feeds.PandasData):
    lines = ('vol_percentile', 'position_size', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('vol_percentile', 6), ('position_size', 7), ('entry_signal', 8), ('exit_signal', 9),
    )


class GoldVolatilityPositionStrategy(bt.Strategy):
    params = dict(
        vol_window=20,
        rank_window=252,
        high_vol_threshold=0.8,
        low_vol_threshold=0.2,
        base_lot_size=1.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
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
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.base_lot_size)))
            return
        
        # 有持仓时检查出场
        if exit_signal:
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
