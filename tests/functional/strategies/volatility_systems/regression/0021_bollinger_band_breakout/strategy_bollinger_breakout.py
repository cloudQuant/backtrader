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


def prepare_bollinger_features(df, params):
    """准备布林带突破策略特征"""
    out = df.copy()
    bb_period = int(params.get('bb_period', 100))
    entry_dev = float(params.get('bb_entry_dev', 3.0))
    exit_dev = float(params.get('bb_exit_dev', 1.0))
    
    # 计算布林带
    out['bb_middle'] = out['close'].rolling(bb_period).mean()
    out['bb_std'] = out['close'].rolling(bb_period).std()
    
    # 入场上轨（3倍标准差）
    out['bb_upper_entry'] = out['bb_middle'] + entry_dev * out['bb_std']
    
    # 出场下轨（1倍标准差）
    out['bb_lower_exit'] = out['bb_middle'] - exit_dev * out['bb_std']
    
    # 入场信号：收盘价突破上轨
    out['entry_signal'] = (out['close'] > out['bb_upper_entry']).astype(float)
    
    # 出场信号：收盘价跌破下轨
    out['exit_signal'] = (out['close'] < out['bb_lower_exit']).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'bb_middle', 'bb_upper_entry', 'bb_lower_exit', 
               'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5BollingerFeed(bt.feeds.PandasData):
    lines = ('bb_middle', 'bb_upper_entry', 'bb_lower_exit', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('bb_middle', 6), ('bb_upper_entry', 7), ('bb_lower_exit', 8),
        ('entry_signal', 9), ('exit_signal', 10),
    )


class BollingerBreakoutStrategy(bt.Strategy):
    params = dict(
        bb_period=100,
        bb_entry_dev=3.0,
        bb_exit_dev=1.0,
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
        
        # 出场优先
        if self.position:
            if float(self.data.exit_signal[0]) > 0.5:
                self.sell_count += 1
                self.pending_order = self.close()
            return
        
        # 入场
        if float(self.data.entry_signal[0]) > 0.5:
            self.buy_count += 1
            self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))

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
