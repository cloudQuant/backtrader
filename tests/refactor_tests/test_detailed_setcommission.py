#!/usr/bin/env python
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
sys.path.insert(0, "tests/original_tests")

import testcommon

import backtrader as bt


def test_parameter_setting_details():
    """详细测试参数设置过程"""
    print("=== 详细测试CommInfo参数设置 ===")

    # 1. 测试直接创建CommInfo对象
    print("\n1. 直接创建CommInfo对象（类似broker.setcommission）:")
    print("   调用: CommInfoBase(commission=2.0, margin=1000.0, mult=10.0)")

    try:
        comminfo = bt.CommInfoBase(commission=2.0, margin=1000.0, mult=10.0)
        print(f"   创建成功!")
        print(f"   commission: {comminfo.get_param('commission')}")
        print(f"   margin: {comminfo.get_param('margin')}")
        print(f"   mult: {comminfo.get_param('mult')}")
        print(f"   stocklike: {comminfo.get_param('stocklike')}")
        print(f"   _stocklike: {comminfo._stocklike}")
        print(f"   _commtype: {comminfo._commtype}")
        print(f"   property stocklike: {comminfo.stocklike}")
        print(f"   property margin: {comminfo.margin}")

        # 测试关键方法
        test_price = 100.0
        test_size = 1
        print(f"\n   测试关键方法 (price={test_price}, size={test_size}):")
        print(f"   getcommission(): {comminfo.getcommission(test_size, test_price)}")
        print(f"   get_margin(): {comminfo.get_margin(test_price)}")
        print(f"   getoperationcost(): {comminfo.getoperationcost(test_size, test_price)}")

    except Exception as e:
        print(f"   创建失败: {e}")
        import traceback

        traceback.print_exc()

    # 2. 测试原始参数创建（对比）
    print("\n\n2. 测试原始参数创建（默认值）:")
    print("   调用: CommInfoBase()")

    try:
        default_comminfo = bt.CommInfoBase()
        print(f"   创建成功!")
        print(f"   commission: {default_comminfo.get_param('commission')}")
        print(f"   margin: {default_comminfo.get_param('margin')}")
        print(f"   mult: {default_comminfo.get_param('mult')}")
        print(f"   stocklike: {default_comminfo.get_param('stocklike')}")
        print(f"   _stocklike: {default_comminfo._stocklike}")
        print(f"   _commtype: {default_comminfo._commtype}")
        print(f"   property stocklike: {default_comminfo.stocklike}")
        print(f"   property margin: {default_comminfo.margin}")

    except Exception as e:
        print(f"   创建失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_parameter_setting_details()
