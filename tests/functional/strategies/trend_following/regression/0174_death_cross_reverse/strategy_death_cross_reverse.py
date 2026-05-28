from __future__ import absolute_import, division, print_function, unicode_literals

import io
import backtrader as bt
import pandas as pd


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


def prepare_death_cross_reverse_features(df, params):
    """准备死叉反向策略特征"""
    out = df.copy()
    fast_period = int(params.get('fast_period', 50))
    slow_period = int(params.get('slow_period', 200))
    
    # 计算快慢均线
    out['ma_fast'] = out['close'].rolling(window=fast_period).mean()
    out['ma_slow'] = out['close'].rolling(window=slow_period).mean()
    
    # 死叉信号：快线下穿慢线（反向做多信号）
    out['death_cross'] = ((out['ma_fast'].shift(1) >= out['ma_slow'].shift(1)) & 
                          (out['ma_fast'] < out['ma_slow'])).astype(float)
    
    # 金叉信号：快线上穿慢线（平仓信号）
    out['golden_cross'] = ((out['ma_fast'].shift(1) <= out['ma_slow'].shift(1)) & 
                           (out['ma_fast'] > out['ma_slow'])).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'ma_fast', 'ma_slow', 'death_cross', 'golden_cross']].copy()
    return out.dropna()


class Mt5DeathCrossReverseFeed(bt.feeds.PandasData):
    lines = ('ma_fast', 'ma_slow', 'death_cross', 'golden_cross',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('ma_fast', 6), ('ma_slow', 7), ('death_cross', 8), ('golden_cross', 9),
    )


class DeathCrossReverseStrategy(bt.Strategy):
    params = dict(
        fast_period=50,
        slow_period=200,
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
        
        death_cross = float(self.data.death_cross[0]) > 0.5
        golden_cross = float(self.data.golden_cross[0]) > 0.5
        
        # 无持仓时检查入场：死叉时反向做多
        if not self.position:
            if death_cross:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
            return
        
        # 有持仓时检查出场：金叉时平仓
        if golden_cross:
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
