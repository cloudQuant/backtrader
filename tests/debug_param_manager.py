#!/usr/bin/env python
import sys
import os
sys.path.insert(0, '.')

import backtrader as bt

def test_param_manager():
    """测试参数管理器是否正常工作"""
    print("=== 测试参数管理器 ===")
    
    # 检查类级别的参数描述符
    print(f"CommInfoBase类描述符: {list(bt.CommInfoBase._parameter_descriptors.keys())}")
    
    # 检查每个描述符的详细信息
    for name, descriptor in bt.CommInfoBase._parameter_descriptors.items():
        print(f"  {name}: default={descriptor.default}, type={descriptor.type_}")
    
    # 创建CommInfo对象并观察参数设置过程
    print("\n创建CommInfo对象: CommInfoBase(margin=1000.0)")
    
    comminfo = bt.CommInfoBase(margin=1000.0)
    
    print(f"参数管理器中的描述符: {list(comminfo._param_manager._descriptors.keys())}")
    print(f"参数管理器中的值: {comminfo._param_manager._values}")
    print(f"参数管理器中的默认值: {comminfo._param_manager._defaults}")
    
    # 测试直接访问类描述符
    print(f"\n直接从类访问margin描述符: {hasattr(bt.CommInfoBase, 'margin')}")
    if hasattr(bt.CommInfoBase, 'margin'):
        print(f"类margin描述符: {bt.CommInfoBase.margin}")
        print(f"margin描述符类型: {type(bt.CommInfoBase.margin)}")
        
    print(f"直接从类访问stocklike描述符: {hasattr(bt.CommInfoBase, 'stocklike')}")
    if hasattr(bt.CommInfoBase, 'stocklike'):
        print(f"类stocklike描述符: {bt.CommInfoBase.stocklike}")
        print(f"stocklike描述符类型: {type(bt.CommInfoBase.stocklike)}")
    
    print(f"直接调用get_param('margin'): {comminfo.get_param('margin')}")
    print(f"通过property访问margin: {comminfo.margin}")
    
    # 手动设置看看是否工作
    print(f"\n手动设置margin为2000.0...")
    comminfo.set_param('margin', 2000.0)
    print(f"设置后get_param('margin'): {comminfo.get_param('margin')}")
    print(f"设置后property margin: {comminfo.margin}")

if __name__ == "__main__":
    test_param_manager() 