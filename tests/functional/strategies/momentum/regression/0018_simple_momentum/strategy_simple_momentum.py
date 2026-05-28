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


def prepare_simple_momentum_features(df, params):
    """准备简单动量策略特征"""
    out = df.copy()
    ndays_high = int(params.get('ndays_high', 5))
    ibs_trigger = float(params.get('ibs_trigger', 0.15))
    
    # 计算IBS (Internal Bar Strength)
    # IBS = (High - Close) / (High - Low)
    # 低IBS表示收盘价接近最高价（强势）
    out['ibs'] = (out['high'] - out['close']) / (out['high'] - out['low'])
    
    # 计算N日最高价
    out['high_n'] = out['high'].rolling(window=ndays_high).max()
    
    # 创N日新高
    out['new_high'] = (out['high'] >= out['high_n']).astype(float)
    
    # 前一日IBS低于阈值
    out['ibs_low'] = (out['ibs'].shift(1) <= ibs_trigger).astype(float)
    
    # 入场信号：创N日新高 + 前一日IBS低
    out['entry_signal'] = ((out['new_high'] > 0.5) & 
                           (out['ibs_low'] > 0.5)).astype(float)
    
    # 出场信号：收盘价高于昨日最高价
    out['exit_signal'] = (out['close'] > out['high'].shift(1)).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'ibs', 'new_high', 'ibs_low', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5SimpleMomentumFeed(bt.feeds.PandasData):
    lines = ('ibs', 'new_high', 'ibs_low', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('ibs', 6), ('new_high', 7), ('ibs_low', 8), 
        ('entry_signal', 9), ('exit_signal', 10),
    )


class SimpleMomentumStrategy(bt.Strategy):
    params = dict(
        ndays_high=5,
        ibs_trigger=0.15,
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
        
        # 固定持有天数出场
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
