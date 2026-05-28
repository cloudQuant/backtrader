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


def prepare_decay_stop_features(df, params):
    """准备策略衰减停止交易特征"""
    out = df.copy()
    lookback = int(params.get('lookback', 252))
    max_drawdown_pct = float(params.get('max_drawdown_pct', 0.20))
    max_drawdown_days = int(params.get('max_drawdown_days', 126))
    
    # 计算累计收益
    out['returns'] = out['close'].pct_change()
    out['cum_returns'] = (1 + out['returns']).cumprod()
    
    # 计算滚动最高点
    out['rolling_max'] = out['cum_returns'].rolling(window=lookback, min_periods=1).max()
    
    # 计算回撤深度
    out['drawdown'] = (out['cum_returns'] - out['rolling_max']) / out['rolling_max']
    
    # 计算回撤持续天数
    out['drawdown_start'] = (out['drawdown'] < 0).astype(int)
    out['drawdown_days'] = out['drawdown_start'].groupby((out['drawdown_start'] == 0).cumsum()).cumsum()
    
    # 判断是否超过最大回撤
    out['exceed_drawdown'] = ((out['drawdown'] < -max_drawdown_pct) | 
                               (out['drawdown_days'] > max_drawdown_days)).astype(float)
    
    # 入场信号：简单趋势跟踪
    out['ma_fast'] = out['close'].rolling(window=20).mean()
    out['ma_slow'] = out['close'].rolling(window=50).mean()
    out['entry_signal'] = ((out['ma_fast'] > out['ma_slow']) & 
                           (out['exceed_drawdown'] < 0.5)).astype(float)
    
    # 出场信号：超过最大回撤
    out['exit_signal'] = (out['exceed_drawdown'] > 0.5).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'drawdown', 'exceed_drawdown', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5DecayStopFeed(bt.feeds.PandasData):
    lines = ('drawdown', 'exceed_drawdown', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('drawdown', 6), ('exceed_drawdown', 7), 
        ('entry_signal', 8), ('exit_signal', 9),
    )


class StrategyDecayStopStrategy(bt.Strategy):
    params = dict(
        lookback=252,
        max_drawdown_pct=0.20,
        max_drawdown_days=126,
        stop_threshold=0.7,
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
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
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
