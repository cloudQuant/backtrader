from __future__ import absolute_import, division, print_function, unicode_literals

import io
import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime


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


def get_holiday_dates(year):
    """获取指定年份的假期日期"""
    holidays = []
    # 新年（1月1日）
    holidays.append(datetime(year, 1, 1))
    # 劳动节（5月1日）
    holidays.append(datetime(year, 5, 1))
    # 美国独立日（7月4日）
    holidays.append(datetime(year, 7, 4))
    # 感恩节（11月第四个周四）
    try:
        thanksgiving = pd.date_range(start=f'{year}-11-01', end=f'{year}-11-30', freq='WOM-4THU')[0]
        holidays.append(thanksgiving)
    except:
        pass
    # 圣诞节（12月25日）
    holidays.append(datetime(year, 12, 25))
    return holidays


def prepare_holiday_reversal_features(df, params):
    """准备假期反转策略特征"""
    out = df.copy()
    lookback = int(params.get('lookback', 20))
    momentum_threshold = float(params.get('momentum_threshold', 0.0))
    
    # 计算动量
    out['momentum'] = out['close'] / out['close'].shift(lookback) - 1
    
    # 标记假期周
    out['is_holiday_week'] = 0.0
    for year in range(out.index[0].year, out.index[-1].year + 1):
        for holiday in get_holiday_dates(year):
            # 假期前一周和假期后一周
            holiday_week_start = holiday - pd.Timedelta(days=7)
            holiday_week_end = holiday + pd.Timedelta(days=7)
            mask = (out.index >= holiday_week_start) & (out.index <= holiday_week_end)
            out.loc[mask, 'is_holiday_week'] = 1.0
    
    # 入场信号：假期周且动量为负（做多）或动量为正（做空，这里简化为做多）
    out['entry_signal'] = ((out['is_holiday_week'] > 0.5) & (out['momentum'] < momentum_threshold)).astype(float)
    
    # 出场信号：持仓期满
    out['exit_signal'] = 0.0
    
    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest', 
               'momentum', 'is_holiday_week', 'entry_signal', 'exit_signal']].copy()
    return out.dropna()


class Mt5HolidayReversalFeed(bt.feeds.PandasData):
    lines = ('momentum', 'is_holiday_week', 'entry_signal', 'exit_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('momentum', 6), ('is_holiday_week', 7), ('entry_signal', 8), ('exit_signal', 9),
    )


class HolidayReversalStrategy(bt.Strategy):
    params = dict(
        lookback=20,
        momentum_threshold=0.0,
        holding_days=4,
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
        
        # 无持仓时检查入场
        if not self.position:
            if entry_signal:
                self.buy_count += 1
                self.entry_bar = self.bar_num
                self.pending_order = self.buy(size=self._get_position_size(target_notional_pct=float(self.p.lot_size)))
            return
        
        # 有持仓时检查出场
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
