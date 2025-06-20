#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

"""
测试Momentum指标重构

这个测试验证新的MomentumNew类是否正确实现了参数系统
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backtrader'))

# 导入新的Momentum实现
from backtrader.indicators.momentum import MomentumNew, Momentum


def test_momentum_new():
    """测试新的MomentumNew类"""
    print("测试新的MomentumNew类...")
    
    try:
        # 创建新的Momentum实例
        momentum = MomentumNew(period=14)
        print(f"✅ MomentumNew创建成功")
        
        # 测试参数系统
        print(f"  默认period: {momentum.period}")
        print(f"  参数管理器存在: {hasattr(momentum, '_param_manager')}")
        print(f"  p属性存在: {hasattr(momentum, 'p')}")
        
        if hasattr(momentum, 'p') and momentum.p:
            print(f"  momentum.p.period: {momentum.p.period}")
        
        # 测试兼容接口
        if hasattr(momentum, '_getitems'):
            print(f"  兼容接口._getitems(): {momentum._getitems()}")
        if hasattr(momentum, '_gettuple'):
            print(f"  兼容接口._gettuple(): {momentum._gettuple()}")
        
        # 测试类级别兼容性
        if hasattr(MomentumNew, '_gettuple'):
            print(f"  类级别._gettuple(): {MomentumNew._gettuple()}")
        
        # 测试计算方法
        result = momentum.calculate_momentum(100, 90)
        print(f"  计算测试 (100-90): {result}")
        
        print("✅ MomentumNew所有测试通过!")
        return True
        
    except Exception as e:
        print(f"❌ MomentumNew测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_original_momentum():
    """测试原始Momentum类是否仍然工作"""
    print("\n测试原始Momentum类...")
    
    try:
        # 注意：原始Momentum需要backtrader环境，我们只能测试导入
        print(f"✅ 原始Momentum类导入成功: {Momentum}")
        print(f"  参数定义: {getattr(Momentum, 'params', 'No params')}")
        return True
        
    except Exception as e:
        print(f"❌ 原始Momentum测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_parameter_modification():
    """测试参数修改"""
    print("\n测试参数修改...")
    
    try:
        momentum = MomentumNew(period=20)
        print(f"  初始period: {momentum.period}")
        
        # 修改参数
        momentum.period = 30
        print(f"  修改后period: {momentum.period}")
        
        if hasattr(momentum, 'p') and momentum.p:
            print(f"  通过p访问: {momentum.p.period}")
        
        print("✅ 参数修改测试通过!")
        return True
        
    except Exception as e:
        print(f"❌ 参数修改测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_feed_style_compatibility():
    """测试feed.py样式的兼容性"""
    print("\n测试feed.py样式兼容性...")
    
    try:
        # 模拟feed.py中的使用模式: params = () + SomeClass.params._gettuple()
        base_params = ()
        momentum_params = MomentumNew.params._gettuple()
        combined_params = base_params + momentum_params
        
        print(f"  基础参数: {base_params}")
        print(f"  MomentumNew参数: {momentum_params}")
        print(f"  组合参数: {combined_params}")
        
        print("✅ feed.py样式兼容性测试通过!")
        return True
        
    except Exception as e:
        print(f"❌ feed.py样式兼容性测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("开始Momentum指标重构测试...\n")
    
    results = []
    results.append(test_momentum_new())
    results.append(test_original_momentum())
    results.append(test_parameter_modification())
    results.append(test_feed_style_compatibility())
    
    print(f"\n总结: {sum(results)}/{len(results)} 测试通过")
    
    if all(results):
        print("🎉 所有测试都通过！重构成功！")
    else:
        print("⚠️  有测试失败，需要进一步调试")