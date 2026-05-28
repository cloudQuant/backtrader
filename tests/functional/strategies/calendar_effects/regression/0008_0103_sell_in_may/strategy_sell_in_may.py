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


def prepare_seasonal_features(df, params):
    """准备季节性策略特征"""
    out = df.copy()
    buy_month = int(params.get('buy_month', 11))
    sell_month = int(params.get('sell_month', 5))
    
    # 提取月份
    out['month'] = out.index.month
    
    # 生成信号：11月买入，5月卖出
    # 持有期：11月-4月
    # 空仓期：5月-10月
    out['signal'] = 0.0
    
    # 买入信号：月份等于买入月份(11月)
    buy_signal = out['month'] == buy_month
    
    # 卖出信号：月份等于卖出月份(5月)
    sell_signal = out['month'] == sell_month
    
    # 只在月份变化时触发信号
    prev_month = out['month'].shift(1)
    
    # 买入信号：进入买入月份
    buy_entry = (prev_month != buy_month) & buy_signal
    
    # 卖出信号：进入卖出月份
    sell_entry = (prev_month != sell_month) & sell_signal
    
    out['buy_signal'] = buy_entry.astype(float)
    out['sell_signal'] = sell_entry.astype(float)
    
    # 持有状态：11月-4月持有
    out['holding'] = ((out['month'] >= buy_month) | (out['month'] <= 4)).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'month', 'buy_signal', 'sell_signal', 'holding']].copy()
    return out.dropna()


class Mt5SeasonalFeed(bt.feeds.PandasData):
    lines = ('month', 'buy_signal', 'sell_signal', 'holding',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month', 6), ('buy_signal', 7), ('sell_signal', 8), ('holding', 9),
    )


class SellInMaySeasonalStrategy(bt.Strategy):
    params = dict(
        buy_month=11,
        sell_month=5,
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
        
        buy_signal = float(self.data.buy_signal[0]) > 0.5
        sell_signal = float(self.data.sell_signal[0]) > 0.5
        
        # 无持仓时检查入场
        if not self.position:
            if buy_signal:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
            return
        
        # 有持仓时检查出场
        if sell_signal:
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
