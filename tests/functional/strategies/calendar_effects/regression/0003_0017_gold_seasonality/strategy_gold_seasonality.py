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


def prepare_seasonality_features(df, params):
    """准备季节性策略特征"""
    out = df.copy()
    
    # 提取月份
    out['month'] = out.index.month
    
    # 印度婚礼季节 (10-12月)
    wedding_start = int(params.get('wedding_season_start', 10))
    wedding_end = int(params.get('wedding_season_end', 12))
    
    # 中国春节前 (12月-2月)
    chinese_start = int(params.get('chinese_new_year_start', 12))
    chinese_end = int(params.get('chinese_new_year_end', 2))
    
    # 季节性信号
    out['wedding_season'] = ((out['month'] >= wedding_start) & 
                              (out['month'] <= wedding_end)).astype(float)
    
    # 中国春节季节 (12月或1-2月)
    out['chinese_season'] = ((out['month'] == chinese_start) | 
                              (out['month'] <= chinese_end)).astype(float)
    
    # 综合季节性信号
    out['seasonality_signal'] = ((out['wedding_season'] > 0.5) | 
                                  (out['chinese_season'] > 0.5)).astype(float)
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'month', 'seasonality_signal']].copy()
    return out


class Mt5SeasonalityFeed(bt.feeds.PandasData):
    lines = ('month', 'seasonality_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('month', 6), ('seasonality_signal', 7),
    )


class GoldSeasonalityStrategy(bt.Strategy):
    params = dict(
        wedding_season_start=10,
        wedding_season_end=12,
        chinese_new_year_start=12,
        chinese_new_year_end=2,
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
        self.last_month = None
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
        
        current_month = int(self.data.month[0])
        seasonality_signal = float(self.data.seasonality_signal[0])
        
        # 月度调仓
        if current_month == self.last_month:
            return
        self.last_month = current_month
        
        # 根据季节性信号调仓
        if seasonality_signal > 0.5:
            # 季节性旺季，持有
            if not self.position:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
        else:
            # 非季节性时期，空仓
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
