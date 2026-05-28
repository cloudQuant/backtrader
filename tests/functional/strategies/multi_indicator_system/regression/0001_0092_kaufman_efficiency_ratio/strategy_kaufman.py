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


def calculate_efficiency_ratio(prices, period=10):
    """计算Kaufman效率比率"""
    change = prices.diff()
    direction = abs(prices - prices.shift(period))
    volatility = change.abs().rolling(window=period).sum()
    er = direction / volatility
    return er


def calculate_kama(prices, er, fast_period=2, slow_period=30):
    """计算Kaufman自适应移动平均"""
    fast_sc = 2 / (fast_period + 1)
    slow_sc = 2 / (slow_period + 1)
    sc = er * (fast_sc - slow_sc) + slow_sc
    sc = sc ** 2
    
    kama = prices.copy()
    kama.iloc[:30] = prices.iloc[:30].mean()
    
    for i in range(30, len(prices)):
        kama.iloc[i] = kama.iloc[i-1] + sc.iloc[i] * (prices.iloc[i] - kama.iloc[i-1])
    
    return kama


def prepare_kaufman_features(df, params):
    """准备Kaufman效率比率策略特征"""
    out = df.copy()
    er_period = int(params.get('er_period', 10))
    fast_period = int(params.get('fast_period', 2))
    slow_period = int(params.get('slow_period', 30))
    
    # 计算效率比率
    out['er'] = calculate_efficiency_ratio(out['close'], er_period)
    
    # 计算KAMA
    out['kama'] = calculate_kama(out['close'], out['er'], fast_period, slow_period)
    
    # 趋势确认信号
    er_threshold = float(params.get('er_threshold', 0.3))
    out['trend_confirmed'] = (out['er'] > er_threshold).astype(float)
    
    # 入场信号：趋势确认 + 价格穿越KAMA
    out['cross_above'] = ((out['close'] > out['kama']) & 
                          (out['close'].shift(1) <= out['kama'].shift(1))).astype(float)
    out['cross_below'] = ((out['close'] < out['kama']) & 
                          (out['close'].shift(1) >= out['kama'].shift(1))).astype(float)
    
    out['entry_long'] = ((out['trend_confirmed'] > 0.5) & 
                         (out['cross_above'] > 0.5)).astype(float)
    out['entry_short'] = ((out['trend_confirmed'] > 0.5) & 
                          (out['cross_below'] > 0.5)).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'er', 'kama', 'entry_long', 'entry_short']].copy()
    return out.dropna()


class Mt5KaufmanFeed(bt.feeds.PandasData):
    lines = ('er', 'kama', 'entry_long', 'entry_short',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('er', 6), ('kama', 7), ('entry_long', 8), ('entry_short', 9),
    )


class KaufmanEfficiencyStrategy(bt.Strategy):
    params = dict(
        er_period=10,
        er_threshold=0.3,
        fast_period=2,
        slow_period=30,
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
        self.position_type = 0  # 1=long, -1=short
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
        
        entry_long = float(self.data.entry_long[0]) > 0.5
        entry_short = float(self.data.entry_short[0]) > 0.5
        close_above_kama = float(self.data.close[0]) > float(self.data.kama[0])
        close_below_kama = float(self.data.close[0]) < float(self.data.kama[0])
        
        # 无持仓时检查入场
        if not self.position:
            if entry_long:
                self.buy_count += 1
                self.position_type = 1
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
            elif entry_short:
                self.sell_count += 1
                self.position_type = -1
                self.pending_order = self.sell(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
            return
        
        # 有持仓时检查出场
        if self.position_type == 1 and close_below_kama:
            self.sell_count += 1
            self.position_type = 0
            self.pending_order = self.close()
        elif self.position_type == -1 and close_above_kama:
            self.buy_count += 1
            self.position_type = 0
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
