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


def prepare_nr7_features(df, params):
    """准备NR7突破策略特征"""
    out = df.copy()
    lookback = int(params.get('lookback', 7))
    atr_period = int(params.get('atr_period', 14))
    
    # 计算每日区间
    out['daily_range'] = out['high'] - out['low']
    
    # NR7条件：当日区间 < 过去6日最小区间
    out['min_range_prev6'] = out['daily_range'].shift(1).rolling(window=lookback-1).min()
    out['nr7'] = (out['daily_range'] < out['min_range_prev6']).astype(float)
    
    # NR7日的高低点
    out['nr7_high'] = out['high'].where(out['nr7'] > 0.5).shift(1)
    out['nr7_low'] = out['low'].where(out['nr7'] > 0.5).shift(1)
    
    # 计算ATR
    tr1 = out['high'] - out['low']
    tr2 = abs(out['high'] - out['close'].shift(1))
    tr3 = abs(out['low'] - out['close'].shift(1))
    out['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    out['atr'] = out['tr'].rolling(window=atr_period).mean()
    
    # 向上突破信号
    out['breakout_up'] = ((out['nr7'].shift(1) > 0.5) & 
                          (out['close'] > out['nr7_high'])).astype(float)
    
    # 向下突破信号
    out['breakout_down'] = ((out['nr7'].shift(1) > 0.5) & 
                            (out['close'] < out['nr7_low'])).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'nr7', 'nr7_high', 'nr7_low', 'atr', 'breakout_up', 'breakout_down']].copy()
    return out.dropna()


class Mt5NR7Feed(bt.feeds.PandasData):
    lines = ('nr7', 'nr7_high', 'nr7_low', 'atr', 'breakout_up', 'breakout_down',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('nr7', 6), ('nr7_high', 7), ('nr7_low', 8), ('atr', 9),
        ('breakout_up', 10), ('breakout_down', 11),
    )


class NR7BreakoutStrategy(bt.Strategy):
    params = dict(
        lookback=7,
        stop_loss_atr=2.5,
        take_profit_atr=4.0,
        time_exit=5,
        atr_period=14,
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
        self.entry_price = None
        self.entry_bar = None
        self.stop_loss = None
        self.take_profit = None
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
        
        # 有持仓时检查出场
        if self.position:
            bars_held = self.bar_num - self.entry_bar
            
            # 止损
            if self.position_type == 1 and self.data.low[0] < self.stop_loss:
                self.pending_order = self.close()
                self.position_type = 0
                return
            elif self.position_type == -1 and self.data.high[0] > self.stop_loss:
                self.pending_order = self.close()
                self.position_type = 0
                return
            
            # 止盈
            if self.position_type == 1 and self.data.high[0] > self.take_profit:
                self.pending_order = self.close()
                self.position_type = 0
                return
            elif self.position_type == -1 and self.data.low[0] < self.take_profit:
                self.pending_order = self.close()
                self.position_type = 0
                return
            
            # 时间出场
            if bars_held >= self.p.time_exit:
                self.pending_order = self.close()
                self.position_type = 0
            return
        
        # 无持仓时检查NR7突破
        atr = float(self.data.atr[0])
        if atr <= 0:
            return
        
        # 向上突破
        if float(self.data.breakout_up[0]) > 0.5:
            self.buy_count += 1
            self.entry_price = float(self.data.close[0])
            self.entry_bar = self.bar_num
            self.stop_loss = self.entry_price - self.p.stop_loss_atr * atr
            self.take_profit = self.entry_price + self.p.take_profit_atr * atr
            self.position_type = 1
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
        
        # 向下突破
        elif float(self.data.breakout_down[0]) > 0.5:
            self.sell_count += 1
            self.entry_price = float(self.data.close[0])
            self.entry_bar = self.bar_num
            self.stop_loss = self.entry_price + self.p.stop_loss_atr * atr
            self.take_profit = self.entry_price - self.p.take_profit_atr * atr
            self.position_type = -1
            self.pending_order = self.sell(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))

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
