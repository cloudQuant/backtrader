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


def calculate_rsi(close, period=2):
    """计算RSI指标"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.inf)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def prepare_mean_reversion_entry_features(df, params):
    """准备均值回归入场策略特征"""
    out = df.copy()
    rsi_period = int(params.get('rsi_period', 2))
    rsi_oversold = float(params.get('rsi_oversold', 10))
    
    # 计算RSI
    out['rsi'] = calculate_rsi(out['close'], rsi_period)
    
    # 计算前一日高点
    out['prev_high'] = out['high'].shift(1)
    
    # 入场信号：RSI超卖
    out['entry_signal'] = (out['rsi'] < rsi_oversold).astype(float)
    
    # 确认入场：价格突破前一日高点
    out['confirmation'] = (out['close'] > out['prev_high']).astype(float)
    
    # 综合入场信号：RSI超卖 + 确认突破
    out['confirmed_entry'] = ((out['entry_signal'] > 0.5) & 
                               (out['confirmation'] > 0.5)).astype(float)
    
    # 出场信号：持有N天后
    out['exit_signal'] = 0.0
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'rsi', 'entry_signal', 'confirmed_entry', 'exit_signal']].copy()
    return out.dropna()


class Mt5MeanReversionEntryFeed(bt.feeds.PandasData):
    lines = ('rsi', 'entry_signal', 'confirmed_entry', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('rsi', 6), ('entry_signal', 7), ('confirmed_entry', 8), ('exit_signal', 9),
    )


class MeanReversionEntryStrategy(bt.Strategy):
    params = dict(
        rsi_period=2,
        rsi_oversold=10,
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
        
        confirmed_entry = float(self.data.confirmed_entry[0]) > 0.5
        
        # 无持仓时检查入场
        if not self.position:
            if confirmed_entry:
                self.buy_count += 1
                self.entry_bar = self.bar_num
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
            return
        
        # 有持仓时检查出场：固定持有天数
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
