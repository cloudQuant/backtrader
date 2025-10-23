#!/usr/bin/env python
import sys
import os
import testcommon
import backtrader as bt

def test_setcommission_behavior():
    """测试setcommission方法的行为"""
    print("=== 测试setcommission方法 ===")
    
    cerebro = bt.Cerebro()
    data = testcommon.getdata(0)
    cerebro.adddata(data)
    
    class TestStrategy(bt.Strategy):
        params = (("stocklike", False),)
        
        def __init__(self):
            pass
            
        def start(self):
            print(f"开始前Broker现金: {self.broker.getcash()}")
            print(f"开始前CommInfo类型: {type(self.broker.getcommissioninfo(self.data)).__name__}")
            
            # 获取默认CommInfo
            default_comminfo = self.broker.getcommissioninfo(self.data)
            print(f"默认CommInfo参数:")
            try:
                print(f"  commission: {default_comminfo.get_param('commission')}")
                print(f"  mult: {default_comminfo.get_param('mult')}")
                print(f"  margin: {default_comminfo.get_param('margin')}")
                print(f"  stocklike: {default_comminfo.get_param('stocklike')}")
                print(f"  _stocklike: {default_comminfo._stocklike}")
                print(f"  _commtype: {default_comminfo._commtype}")
            except Exception as e:
                print(f"  获取默认参数失败: {e}")
                # 尝试原始方式
                try:
                    print(f"  p.commission: {default_comminfo.p.commission}")
                    print(f"  p.mult: {default_comminfo.p.mult}")
                    print(f"  p.margin: {default_comminfo.p.margin}")
                    print(f"  p.stocklike: {default_comminfo.p.stocklike}")
                except Exception as e2:
                    print(f"  原始参数访问也失败: {e2}")
            
            # 设置自定义commission
            print(f"\n调用setcommission(commission=2.0, mult=10.0, margin=1000.0)...")
            if not self.p.stocklike:
                self.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)
                
            print(f"设置后Broker现金: {self.broker.getcash()}")
            print(f"设置后CommInfo类型: {type(self.broker.getcommissioninfo(self.data)).__name__}")
            
            # 获取设置后的CommInfo
            new_comminfo = self.broker.getcommissioninfo(self.data)
            print(f"新CommInfo参数:")
            try:
                print(f"  commission: {new_comminfo.get_param('commission')}")
                print(f"  mult: {new_comminfo.get_param('mult')}")
                print(f"  margin: {new_comminfo.get_param('margin')}")
                print(f"  stocklike: {new_comminfo.get_param('stocklike')}")
                print(f"  _stocklike: {new_comminfo._stocklike}")
                print(f"  _commtype: {new_comminfo._commtype}")
            except Exception as e:
                print(f"  获取新参数失败: {e}")
                # 尝试原始方式
                try:
                    print(f"  p.commission: {new_comminfo.p.commission}")
                    print(f"  p.mult: {new_comminfo.p.mult}")
                    print(f"  p.margin: {new_comminfo.p.margin}")
                    print(f"  p.stocklike: {new_comminfo.p.stocklike}")
                except Exception as e2:
                    print(f"  原始参数访问也失败: {e2}")
                    
            # 测试关键方法
            test_price = 100.0
            test_size = 1
            print(f"\n测试关键方法 (price={test_price}, size={test_size}):")
            print(f"  getcommission(): {new_comminfo.getcommission(test_size, test_price)}")
            print(f"  get_margin(): {new_comminfo.get_margin(test_price)}")
            print(f"  getoperationcost(): {new_comminfo.getoperationcost(test_size, test_price)}")
        
        def next(self):
            pass  # 避免运行整个策略
            
        def stop(self):
            print("策略结束")
    
    cerebro.addstrategy(TestStrategy)
    result = cerebro.run()
    print(f"运行完成")

if __name__ == "__main__":
    test_setcommission_behavior() 