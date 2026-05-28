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


def prepare_double_7s_features(df, params):
    """准备双7策略特征"""
    out = df.copy()
    sma_period = int(params.get('sma_period', 200))
    n_low = int(params.get('n_low', 7))
    n_high = int(params.get('n_high', 7))
    
    # 趋势过滤：200日均线
    out['sma'] = out['close'].rolling(sma_period).mean()
    
    # N日低点和高点
    out['n_day_low'] = out['close'].rolling(n_low).min()
    out['n_day_high'] = out['close'].rolling(n_high).max()
    
    # 入场信号：收盘价 > SMA 且 收盘价 <= 7日低点
    out['buy_signal'] = ((out['close'] > out['sma']) & 
                         (out['close'] <= out['n_day_low'])).astype(float)
    
    # 出场信号：收盘价 >= 7日高点
    out['sell_signal'] = (out['close'] >= out['n_day_high']).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'sma', 'n_day_low', 'n_day_high', 'buy_signal', 'sell_signal']].copy()
    return out.dropna()


class Mt5Double7sFeed(bt.feeds.PandasData):
    lines = ('sma', 'n_day_low', 'n_day_high', 'buy_signal', 'sell_signal',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('sma', 6),
        ('n_day_low', 7),
        ('n_day_high', 8),
        ('buy_signal', 9),
        ('sell_signal', 10),
    )


class Double7sMeanReversionStrategy(bt.Strategy):
    params = dict(
        sma_period=200,
        n_low=7,
        n_high=7,
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
                self.log(f'exit signal: close >= 7-day high')
            return
        
        # 入场
        if float(self.data.buy_signal[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
            self.log(f'entry signal: close <= 7-day low, close > SMA')

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
