#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

"""
测试新旧参数系统的兼容性

这个测试文件用于验证新的ParameterizedBase系统是否能够与
现有的MetaParams系统兼容工作。
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backtrader'))

# 导入新的参数系统
from backtrader.parameters import ParameterizedBase, ParameterDescriptor

# 导入现有的元类系统
from backtrader.metabase import MetaParams, AutoInfoClass
from backtrader.utils.py3 import with_metaclass


class OldStyleClass(with_metaclass(MetaParams, object)):
    """使用旧MetaParams系统的类"""
    params = (
        ('period', 14),
        ('threshold', 0.5),
        ('name', 'test'),
    )


class NewStyleClass(ParameterizedBase):
    """使用新ParameterizedBase系统的类"""
    
    # 使用新的参数描述器
    period = ParameterDescriptor(default=14, type_=int, doc="Period parameter")
    threshold = ParameterDescriptor(default=0.5, type_=float, doc="Threshold parameter")
    name = ParameterDescriptor(default='test', type_=str, doc="Name parameter")


def test_compatibility():
    """测试新旧系统的兼容性"""
    print("测试新旧参数系统兼容性...")
    
    # 测试旧系统
    print("\n1. 测试旧系统:")
    old_obj = OldStyleClass()
    print(f"  旧对象参数: {old_obj.params._getitems()}")
    print(f"  旧对象._gettuple(): {old_obj.params._gettuple()}")
    print(f"  旧对象.p.period: {old_obj.p.period}")
    
    # 测试新系统
    print("\n2. 测试新系统:")
    try:
        new_obj = NewStyleClass()
        print(f"  新对象创建成功")
        
        # 测试兼容接口
        if hasattr(new_obj, '_getitems'):
            print(f"  新对象._getitems(): {new_obj._getitems()}")
        if hasattr(new_obj, '_gettuple'):
            print(f"  新对象._gettuple(): {new_obj._gettuple()}")
        if hasattr(new_obj, 'p') and new_obj.p:
            print(f"  新对象.p.period: {new_obj.p.period}")
            
    except Exception as e:
        print(f"  新对象创建失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 测试类级别接口兼容性
    print("\n3. 测试类级别接口:")
    try:
        if hasattr(OldStyleClass, 'params'):
            print(f"  旧类.params._gettuple(): {OldStyleClass.params._gettuple()}")
        
        if hasattr(NewStyleClass, '_gettuple'):
            print(f"  新类._gettuple(): {NewStyleClass._gettuple()}")
        else:
            print("  新类缺少_gettuple方法")
            
    except Exception as e:
        print(f"  类级别接口测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    test_compatibility()