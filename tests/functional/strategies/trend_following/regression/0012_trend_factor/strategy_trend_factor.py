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


def prepare_trend_factor_features(df, params):
    """准备趋势因子策略特征"""
    out = df.copy()
    lookback_3m = int(params.get('lookback_3m', 63))
    lookback_6m = int(params.get('lookback_6m', 126))
    lookback_12m = int(params.get('lookback_12m', 252))
    w1 = float(params.get('w1', 0.2))
    w2 = float(params.get('w2', 0.3))
    w3 = float(params.get('w3', 0.5))
    threshold = float(params.get('threshold', 0.0))
    
    # 计算时间序列动量 (TSM)
    out['tsm_3m'] = out['close'] / out['close'].shift(lookback_3m) - 1
    out['tsm_6m'] = out['close'] / out['close'].shift(lookback_6m) - 1
    out['tsm_12m'] = out['close'] / out['close'].shift(lookback_12m) - 1
    
    # 计算移动平均趋势
    out['ma_3m'] = out['close'] / out['close'].rolling(window=lookback_3m).mean() - 1
    out['ma_6m'] = out['close'] / out['close'].rolling(window=lookback_6m).mean() - 1
    out['ma_12m'] = out['close'] / out['close'].rolling(window=lookback_12m).mean() - 1
    
    # 构建趋势因子：多周期组合
    out['trend_factor'] = (w1 * out['tsm_3m'] + w2 * out['tsm_6m'] + w3 * out['tsm_12m'])
    
    # 标准化趋势因子
    out['trend_zscore'] = (out['trend_factor'] - out['trend_factor'].rolling(window=252).mean()) / \
                          out['trend_factor'].rolling(window=252).std()
    
    # 生成入场信号：趋势因子大于阈值
    out['entry_signal'] = (out['trend_factor'] > threshold).astype(float)
    
    # 生成出场信号：趋势因子小于阈值
    out['exit_signal'] = (out['trend_factor'] < threshold).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'trend_factor', 'trend_zscore', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5TrendFactorFeed(bt.feeds.PandasData):
    lines = ('trend_factor', 'trend_zscore', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('trend_factor', 6), ('trend_zscore', 7), 
        ('entry_signal', 8), ('exit_signal', 9),
    )


class TrendFactorStrategy(bt.Strategy):
    params = dict(
        lookback_3m=63,
        lookback_6m=126,
        lookback_12m=252,
        w1=0.2,
        w2=0.3,
        w3=0.5,
        threshold=0.0,
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
