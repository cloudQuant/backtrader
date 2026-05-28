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


def prepare_consecutive_down_features(df, params):
    """准备连续下跌日均值回归策略特征"""
    out = df.copy()
    threshold = float(params.get('down_day_threshold', -0.001))
    
    # 计算日收益率
    out['daily_return'] = out['close'].pct_change()
    
    # 判断是否为下跌日
    out['is_down_day'] = (out['daily_return'] < threshold).astype(float)
    
    # 计算连续下跌天数
    out['consecutive_down'] = 0
    count = 0
    for i in range(len(out)):
        if out['is_down_day'].iloc[i] > 0.5:
            count += 1
        else:
            count = 0
        out.loc[out.index[i], 'consecutive_down'] = count
    
    # 入场信号：连续下跌天数在[min, max]范围内
    min_days = int(params.get('min_consecutive_days', 3))
    max_days = int(params.get('max_consecutive_days', 5))
    out['entry_signal'] = ((out['consecutive_down'] >= min_days) & 
                           (out['consecutive_down'] <= max_days)).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'daily_return', 'consecutive_down', 'entry_signal']].copy()
    return out.dropna()


class Mt5ConsecutiveDownFeed(bt.feeds.PandasData):
    lines = ('daily_return', 'consecutive_down', 'entry_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('daily_return', 6), ('consecutive_down', 7), ('entry_signal', 8),
    )


class ConsecutiveDownDaysStrategy(bt.Strategy):
    params = dict(
        down_day_threshold=-0.001,
        min_consecutive_days=3,
        max_consecutive_days=5,
        holding_period=1,
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
        self.entry_bar = None
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
        
        # 有持仓时检查出场
        if self.position:
            bars_held = self.bar_num - self.entry_bar
            if bars_held >= self.p.holding_period:
                self.sell_count += 1
                self.pending_order = self.close()
            return
        
        # 无持仓时检查入场
        if float(self.data.entry_signal[0]) > 0.5:
            self.buy_count += 1
            self.entry_bar = self.bar_num
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
