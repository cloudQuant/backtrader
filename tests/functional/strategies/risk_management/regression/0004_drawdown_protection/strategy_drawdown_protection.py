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


def prepare_drawdown_protection_features(df, params):
    """准备回撤保护策略特征"""
    out = df.copy()
    vol_lookback = int(params.get('vol_lookback', 20))
    
    # 计算收益率
    out['returns'] = out['close'].pct_change()
    
    # 计算波动率（年化）
    out['volatility'] = out['returns'].rolling(vol_lookback).std() * np.sqrt(252)
    
    # 计算回撤
    out['cummax'] = out['close'].cummax()
    out['drawdown'] = (out['close'] - out['cummax']) / out['cummax']
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'returns', 'volatility', 'drawdown']].copy()
    return out.dropna()


class Mt5DrawdownFeed(bt.feeds.PandasData):
    lines = ('returns', 'volatility', 'drawdown',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('returns', 6), ('volatility', 7), ('drawdown', 8),
    )


class DrawdownProtectionStrategy(bt.Strategy):
    params = dict(
        target_vol=0.12,
        max_drawdown=0.15,
        dd_threshold_1=0.03,
        dd_threshold_2=0.06,
        dd_threshold_3=0.10,
        position_level_1=1.0,
        position_level_2=0.75,
        position_level_3=0.5,
        position_level_4=0.25,
        vol_lookback=20,
        smoothing_factor=0.15,
        lot_size=1.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.rebalance_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.current_position_pct = 0.0
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

    def get_position_from_drawdown(self, drawdown):
        """根据回撤确定目标仓位"""
        if drawdown < -self.p.dd_threshold_1:
            return self.p.position_level_1
        elif drawdown < -self.p.dd_threshold_2:
            return self.p.position_level_2
        elif drawdown < -self.p.dd_threshold_3:
            return self.p.position_level_3
        else:
            return self.p.position_level_4

    def get_position_from_volatility(self, current_vol):
        """根据波动率确定目标仓位"""
        if current_vol > 0:
            vol_position = self.p.target_vol / current_vol
            return max(0.25, min(1.0, vol_position))
        return 1.0

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        
        if self.pending_order is not None:
            return
        
        current_vol = float(self.data.volatility[0])
        current_dd = float(self.data.drawdown[0])
        
        # 根据回撤和波动率确定目标仓位
        dd_position = self.get_position_from_drawdown(current_dd)
        vol_position = self.get_position_from_volatility(current_vol)
        target_position = min(dd_position, vol_position)
        
        # 平滑调整
        smoothed_position = (
            self.current_position_pct * (1 - self.p.smoothing_factor) +
            target_position * self.p.smoothing_factor
        )
        
        # 执行调仓
        if abs(smoothed_position - self.current_position_pct) > 0.05:
            self.rebalance_count += 1
            target_size = self._get_position_size(target_notional_pct=smoothed_position * float(self.p.lot_size))
            
            if self.position:
                if smoothed_position < 0.1:
                    self.pending_order = self.close()
                    self.current_position_pct = 0.0
                else:
                    self.pending_order = self.order_target_size(target=target_size)
                    self.current_position_pct = smoothed_position
            else:
                if smoothed_position > 0.1:
                    self.pending_order = self.buy(size=target_size)
                    self.current_position_pct = smoothed_position

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
