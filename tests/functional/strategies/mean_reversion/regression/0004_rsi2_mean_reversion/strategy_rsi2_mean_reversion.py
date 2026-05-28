from __future__ import absolute_import, division, print_function, unicode_literals

import io
import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
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
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def compute_rsi(close, period=2):
    """计算RSI指标"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_atr(high, low, close, period=10):
    """计算ATR指标"""
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(period).mean()
    return atr


def prepare_rsi2_features(df, params):
    """准备RSI2策略特征"""
    out = df.copy()
    rsi_period = int(params.get('rsi_period', 2))
    rsi_buy = float(params.get('rsi_buy_threshold', 5))
    rsi_sell = float(params.get('rsi_sell_threshold', 30))
    sma_period = int(params.get('sma_period', 100))
    atr_period = int(params.get('atr_period', 10))
    atr_multiplier = float(params.get('atr_multiplier', 0.5))
    
    # 计算RSI
    out['rsi'] = compute_rsi(out['close'], rsi_period)
    
    # 趋势过滤
    out['sma'] = out['close'].rolling(sma_period).mean()
    
    # 计算ATR
    out['atr'] = compute_atr(out['high'], out['low'], out['close'], atr_period)
    
    # 入场信号：RSI < 买入阈值 且 收盘价 > SMA
    out['buy_signal'] = ((out['rsi'] < rsi_buy) & 
                         (out['close'] > out['sma'])).astype(float)
    
    # 出场信号：RSI > 卖出阈值
    out['sell_signal'] = (out['rsi'] > rsi_sell).astype(float)
    
    # 限价买入价格：次日开盘价 - ATR调整
    out['limit_price'] = out['open'].shift(-1) - atr_multiplier * out['atr']
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'rsi', 'sma', 'atr', 'buy_signal', 'sell_signal', 'limit_price']].copy()
    return out.dropna()


class Mt5RSI2Feed(bt.feeds.PandasData):
    lines = ('rsi', 'sma', 'atr', 'buy_signal', 'sell_signal', 'limit_price',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('rsi', 6),
        ('sma', 7),
        ('atr', 8),
        ('buy_signal', 9),
        ('sell_signal', 10),
        ('limit_price', 11),
    )


class RSI2MeanReversionStrategy(bt.Strategy):
    params = dict(
        rsi_period=2,
        rsi_buy_threshold=5,
        rsi_sell_threshold=30,
        sma_period=100,
        atr_period=10,
        atr_multiplier=0.5,
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

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        
        if self.pending_order is not None:
            return
        
        # 出场优先
        if self.position:
            if float(self.data.sell_signal[0]) > 0.5:
                self.sell_count += 1
                self.pending_order = self.close()
                self.log(f'exit signal: RSI > {self.p.rsi_sell_threshold}')
            return
        
        # 入场：市价买入（简化，不用限价单）
        if float(self.data.buy_signal[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
            self.log(f'entry signal: RSI={float(self.data.rsi[0]):.2f} < {self.p.rsi_buy_threshold}')

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
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
