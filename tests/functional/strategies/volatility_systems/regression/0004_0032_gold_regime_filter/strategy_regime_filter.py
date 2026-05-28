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


def hurst_exponent(series, window):
    """简化版Hurst指数计算"""
    if len(series) < window:
        return 0.5
    lags = range(2, min(window, 20))
    tau = [np.std(np.subtract(series[lag:], series[:-lag])) for lag in lags]
    if len(tau) < 2 or any(t == 0 for t in tau):
        return 0.5
    log_lags = np.log(lags)
    log_tau = np.log(tau)
    poly = np.polyfit(log_lags, log_tau, 1)
    return poly[0]


def prepare_regime_features(df, params):
    """准备市场状态过滤器特征"""
    out = df.copy()
    short_window = int(params.get('short_window', 10))
    smooth_window = int(params.get('smooth_window', 60))
    rank_window = int(params.get('rank_window', 252))
    
    # 计算收益率
    out['returns'] = out['close'].pct_change()
    
    # 计算滚动Hurst指数
    out['hurst'] = out['returns'].rolling(window=short_window * 10).apply(
        lambda x: hurst_exponent(x, short_window), raw=False
    )
    
    # 平滑Hurst指数
    out['hurst_smooth'] = out['hurst'].rolling(window=smooth_window).mean()
    
    # 百分排名
    out['hurst_rank'] = out['hurst_smooth'].rolling(window=rank_window).rank(pct=True)
    
    # 标准化信号 [-0.5, 0.5]
    out['regime_signal'] = out['hurst_rank'] - 0.5
    
    # 市场状态：正值=趋势期，负值=震荡期
    out['is_trending'] = (out['regime_signal'] > 0).astype(float)
    
    # 趋势方向（使用SMA）
    out['sma_50'] = out['close'].rolling(window=50).mean()
    out['trend_direction'] = (out['close'] > out['sma_50']).astype(float)
    
    # 入场信号：趋势期+上升趋势
    out['entry_signal'] = ((out['is_trending'] > 0.5) & 
                           (out['trend_direction'] > 0.5)).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'regime_signal', 'is_trending', 'entry_signal']].copy()
    return out.dropna()


class Mt5RegimeFeed(bt.feeds.PandasData):
    lines = ('regime_signal', 'is_trending', 'entry_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('regime_signal', 6), ('is_trending', 7), ('entry_signal', 8),
    )


class GoldRegimeFilterStrategy(bt.Strategy):
    params = dict(
        short_window=10,
        smooth_window=60,
        rank_window=252,
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
        self.last_regime = None
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
        
        is_trending = float(self.data.is_trending[0]) > 0.5
        entry_signal = float(self.data.entry_signal[0]) > 0.5
        
        # 状态变化时调仓
        current_regime = 1 if is_trending else 0
        if current_regime == self.last_regime:
            return
        self.last_regime = current_regime
        
        if is_trending and entry_signal:
            # 趋势期，入场
            if not self.position:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
        else:
            # 震荡期，空仓
            if self.position:
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
