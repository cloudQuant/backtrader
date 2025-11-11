#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""调试停牌期间订单不执行的问题"""

import datetime
import pandas as pd
import backtrader as bt
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

# 直接定义所需的类和函数
class ExtendPandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', -1),
        ('pure_bond_value', 5),
        ('convert_value', 6),
        ('pure_bond_premium_rate', 7),
        ('convert_premium_rate', 8)
    )
    lines = ('pure_bond_value', 'convert_value', 'pure_bond_premium_rate', 'convert_premium_rate')

def resolve_data_path(filename):
    search_paths = [
        Path(__file__).parent / "examples" / filename,
        Path(__file__).parent / filename,
    ]
    for candidate in search_paths:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"找不到文件: {filename}")

class DebugStrategy(bt.Strategy):
    def log(self, txt, dt=None):
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print(f'{dt.isoformat()}, {txt}')

    def __init__(self):
        self.order = None
        
    def next(self):
        current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")
        
        # 寻找110056数据
        target_data = None
        for data in self.datas:
            if hasattr(data, '_name') and data._name == '110056':
                target_data = data
                break
        
        if target_data is None:
            return
            
        target_date = target_data.datetime.date(0).strftime("%Y-%m-%d")
        
        # 在2019-05-31发送订单
        if current_date == '2019-05-31' and self.order is None:
            self.log(f"发送订单 on {current_date}, 目标数据日期: {target_date}")
            self.log(f"创建订单时 data.datetime[0] = {target_data.datetime[0]}")
            self.log(f"创建订单时 data.datetime.datetime() = {bt.num2date(target_data.datetime[0])}")
            self.order = self.buy(data=target_data, size=100)
            
        # 记录2019-06-18的信息
        if current_date == '2019-06-18':
            self.log(f"复牌日 {current_date}, 目标数据日期: {target_date}")
            if current_date == target_date:
                self.log(f"复牌时 data.datetime[0] = {target_data.datetime[0]}")
                self.log(f"复牌时 data.datetime.datetime() = {bt.num2date(target_data.datetime[0])}")
                if self.order:
                    self.log(f"订单状态: {self.order.getstatusname()}")
                    self.log(f"订单创建时间: {self.order.created.dt}")
                    self.log(f"订单创建datetime: {bt.num2date(self.order.created.dt)}")
                    self.log(f"比较: data.datetime[0] ({target_data.datetime[0]}) vs order.created.dt ({self.order.created.dt})")
                    self.log(f"条件检查: data.datetime[0] <= order.created.dt ? {target_data.datetime[0] <= self.order.created.dt}")

    def notify_order(self, order):
        if order.status in [order.Completed]:
            dt = bt.num2date(order.executed.dt)
            self.log(f"订单执行 at {dt.isoformat()}, price={order.executed.price}")


def main():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(DebugStrategy)
    
    # 加载指数数据
    index_data = pd.read_csv(resolve_data_path('bond_index_000000.csv'))
    index_data.index = pd.to_datetime(index_data['datetime'])
    index_data = index_data[index_data.index > pd.to_datetime("2019-05-01")]
    index_data = index_data[index_data.index < pd.to_datetime("2019-07-01")]
    index_data = index_data.drop(['datetime'], axis=1)
    feed = ExtendPandasFeed(dataname=index_data)
    cerebro.adddata(feed, name='000000')
    
    # 只加载110056数据
    df = pd.read_csv(resolve_data_path('bond_merged_all_data.csv'))
    # BOND_CODE,BOND_SYMBOL,TRADE_DATE,OPEN_PRICE...
    df.columns = [col.lower() for col in df.columns]
    df = df.rename(columns={'bond_code': 'symbol', 'trade_date': 'datetime',
                            'open_price': 'open', 'high_price': 'high',
                            'low_price': 'low', 'close_price': 'close'})
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df[df['symbol'] == 110056]
    df = df.set_index('datetime')
    df = df.drop(['symbol', 'bond_symbol'], axis=1)
    df = df.dropna()
    df = df.astype("float")
    
    print(f"110056数据范围:")
    print(df.index)
    print()
    
    feed = ExtendPandasFeed(dataname=df)
    cerebro.adddata(feed, name='110056')
    
    cerebro.broker.setcash(1000000.0)
    print("开始运行...")
    cerebro.run()
    print("结束")

if __name__ == "__main__":
    main()
