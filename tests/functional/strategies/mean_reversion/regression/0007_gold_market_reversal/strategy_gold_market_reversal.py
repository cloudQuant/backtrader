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


def count_drawdowns(price, window, threshold):
    """计算窗口内超过阈值的回调次数"""
    roll_max = price.rolling(window=window, min_periods=1).max()
    drawdown = (price - roll_max) / roll_max
    # 统计回调次数
    count = 0
    in_drawdown = False
    for dd in drawdown.iloc[-window:]:
        if dd < threshold and not in_drawdown:
            count += 1
            in_drawdown = True
        elif dd >= threshold * 0.5:
            in_drawdown = False
    return count


def prepare_gold_market_reversal_features(df, params):
    """准备黄金市场反转策略特征"""
    out = df.copy()
    lookback = int(params.get('lookback', 756))
    drawdown_threshold = float(params.get('drawdown_threshold', -0.10))
    min_reversals = int(params.get('min_reversals', 2))
    
    # 计算滚动最大值和回撤
    out['roll_max'] = out['close'].rolling(window=lookback, min_periods=1).max()
    out['drawdown'] = (out['close'] - out['roll_max']) / out['roll_max']
    
    # 计算反转次数（简化版）
    out['reversal_count'] = out['drawdown'].rolling(window=lookback).apply(
        lambda x: count_drawdowns(pd.Series(x), len(x), drawdown_threshold) if len(x) > 0 else 0
    )
    
    # 极端状态：反转次数少于阈值
    out['is_extreme'] = (out['reversal_count'] < min_reversals).astype(float)
    
    # 入场信号：极端状态且当前有回调
    out['entry_signal'] = (
        (out['is_extreme'] > 0.5) & 
        (out['drawdown'] < drawdown_threshold * 0.5)
    ).astype(float)
    
    # 出场信号：价格回归到滚动最大值附近
    out['exit_signal'] = (out['drawdown'] > -0.05).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'drawdown', 'reversal_count', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5GoldMarketReversalFeed(bt.feeds.PandasData):
    lines = ('drawdown', 'reversal_count', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('drawdown', 6), ('reversal_count', 7), ('entry_signal', 8), ('exit_signal', 9),
    )


class GoldMarketReversalStrategy(bt.Strategy):
    params = dict(
        lookback=756,
        drawdown_threshold=-0.10,
        min_reversals=2,
        holding_days=30,
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
