#!/usr/bin/env python
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
sys.path.insert(0, "tests/original_tests")

import testcommon

import backtrader as bt


def compare_comminfo_implementations():
    """比较新旧CommInfo实现的详细行为"""
    print("=== CommInfo实现对比分析 ===")

    # 测试默认的CommInfo对象
    print("\n1. 创建默认CommInfo对象:")

    # 测试原始实现 - 使用原始文件
    print("  切换到原始实现...")

    # 创建新的CommInfo对象
    comminfo_new = bt.CommInfoBase()

    print(f"  新实现默认参数:")
    for param_name in ["commission", "mult", "margin", "commtype", "stocklike", "percabs"]:
        try:
            value = comminfo_new.get_param(param_name)
            print(f"    {param_name}: {value} (type: {type(value).__name__})")
        except Exception as e:
            print(f"    {param_name}: ERROR - {e}")

    print(f"  新实现内部状态:")
    print(f"    _stocklike: {getattr(comminfo_new, '_stocklike', 'MISSING')}")
    print(f"    _commtype: {getattr(comminfo_new, '_commtype', 'MISSING')}")

    # 测试关键方法
    print(f"\n2. 测试关键方法:")
    test_size = 100
    test_price = 50.0

    print(f"  测试参数: size={test_size}, price={test_price}")
    print(f"  getcommission(): {comminfo_new.getcommission(test_size, test_price)}")
    print(f"  get_margin(): {comminfo_new.get_margin(test_price)}")
    print(f"  getoperationcost(): {comminfo_new.getoperationcost(test_size, test_price)}")
    print(f"  getvaluesize(): {comminfo_new.getvaluesize(test_size, test_price)}")

    # 测试property访问
    print(f"\n3. 测试属性访问:")
    try:
        print(f"  .margin: {comminfo_new.margin}")
    except AttributeError as e:
        print(f"  .margin: ERROR - {e}")

    try:
        print(f"  .stocklike: {comminfo_new.stocklike}")
    except AttributeError as e:
        print(f"  .stocklike: ERROR - {e}")

    # 测试.p访问
    print(f"\n4. 测试.p访问:")
    try:
        print(f"  .p.commission: {comminfo_new.p.commission}")
        print(f"  .p.margin: {comminfo_new.p.margin}")
        print(f"  .p.stocklike: {comminfo_new.p.stocklike}")
    except Exception as e:
        print(f"  .p访问: ERROR - {e}")


def test_broker_integration():
    """测试与Broker的集成"""
    print("\n=== 测试Broker集成 ===")

    cerebro = bt.Cerebro()
    data = testcommon.getdata(0)
    cerebro.adddata(data)

    # 添加简单策略来检查broker行为
    class TestStrategy(bt.Strategy):
        def __init__(self):
            pass

        def start(self):
            print(f"  Broker初始现金: {self.broker.getcash()}")
            print(f"  Broker初始价值: {self.broker.getvalue()}")

            # 检查CommInfo
            broker_comminfo = self.broker.getcommissioninfo(self.data)
            print(f"  Broker CommInfo类型: {type(broker_comminfo).__name__}")
            print(
                f"  Broker CommInfo commission: {broker_comminfo.get_param('commission') if hasattr(broker_comminfo, 'get_param') else getattr(broker_comminfo, 'p', {}).commission}"
            )
            print(
                f"  Broker CommInfo margin: {broker_comminfo.get_param('margin') if hasattr(broker_comminfo, 'get_param') else getattr(broker_comminfo, 'p', {}).margin}"
            )
            print(
                f"  Broker CommInfo stocklike: {broker_comminfo.get_param('stocklike') if hasattr(broker_comminfo, 'get_param') else getattr(broker_comminfo, 'p', {}).stocklike}"
            )

    cerebro.addstrategy(TestStrategy)
    cerebro.run()


if __name__ == "__main__":
    compare_comminfo_implementations()
    test_broker_integration()
