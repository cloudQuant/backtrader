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


def calculate_roc(prices, period=3):
    """计算变化率（ROC）"""
    return 100 * (prices / prices.shift(period) - 1)


def calculate_percent_rank(series, window=252):
    """计算PercentRank"""
    def rank_current(x):
        # x是numpy数组
        if x is None or len(x) == 0:
            return np.nan
        current = x[-1]
        if np.isnan(current):
            return np.nan
        count_less_equal = np.sum(x <= current)
        return 100 * count_less_equal / len(x)
    
    return series.rolling(window).apply(rank_current, raw=True)


def prepare_roc_features(df, params):
    """准备ROC均值回归策略特征"""
    out = df.copy()
    roc_period = int(params.get('roc_period', 3))
    rank_window = int(params.get('rank_window', 252))
    entry_threshold = float(params.get('entry_threshold', 15))
    exit_threshold = float(params.get('exit_threshold', 50))
    use_trend_filter = params.get('use_trend_filter', True)
    ma_period = int(params.get('ma_period', 200))
    
    # 计算ROC
    out['roc'] = calculate_roc(out['close'], roc_period)
    
    # 计算PercentRank
    out['percent_rank'] = calculate_percent_rank(out['roc'], rank_window)
    
    # 趋势过滤
    if use_trend_filter:
        out['ma'] = out['close'].rolling(window=ma_period).mean()
        out['uptrend'] = (out['close'] > out['ma']).astype(float)
    else:
        out['uptrend'] = 1.0
    
    # 入场信号：上升趋势 + PercentRank < 阈值
    out['entry_signal'] = ((out['uptrend'] > 0.5) & 
                           (out['percent_rank'] < entry_threshold)).astype(float)
    
    # 出场信号：PercentRank > 出场阈值
    out['exit_signal'] = (out['percent_rank'] > exit_threshold).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'percent_rank', 'uptrend', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5ROCFeed(bt.feeds.PandasData):
    lines = ('percent_rank', 'uptrend', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('percent_rank', 6), ('uptrend', 7), ('entry_signal', 8), ('exit_signal', 9),
    )


class ROCMeanReversionStrategy(bt.Strategy):
    params = dict(
        roc_period=3,
        rank_window=252,
        entry_threshold=15,
        exit_threshold=50,
        holding_period=5,
        use_trend_filter=True,
        ma_period=200,
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
        if exit_signal or holding_days >= self.p.holding_period:
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
