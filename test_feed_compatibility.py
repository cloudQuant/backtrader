#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

"""
测试feed.py中失败场景的兼容性

这个测试模拟feed.py:693行的失败情况:
params = () + DataBase.params._gettuple()
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backtrader'))

# 导入新的参数系统
from backtrader.parameters import ParameterizedBase, ParameterDescriptor

# 导入现有的元类系统
from backtrader.metabase import MetaParams
from backtrader.utils.py3 import with_metaclass


class DataBase(ParameterizedBase):
    """使用新系统的DataBase模拟类"""
    
    # 模拟DataBase的参数
    dataname = ParameterDescriptor(default=None, doc="Data name")
    fromdate = ParameterDescriptor(default=None, doc="From date")
    todate = ParameterDescriptor(default=None, doc="To date")


class FeedBase(with_metaclass(MetaParams, object)):
    """模拟FeedBase类，使用旧系统但依赖DataBase"""
    
    # 这行代码之前会失败: AttributeError: 'tuple' object has no attribute '_gettuple'
    params = () + DataBase.params._gettuple()


def test_feed_compatibility():
    """测试feed.py兼容性场景"""
    print("测试Feed兼容性场景...")
    
    try:
        print(f"DataBase.params类型: {type(DataBase.params)}")
        print(f"DataBase.params._gettuple(): {DataBase.params._gettuple()}")
        
        # 模拟feed.py中的失败行
        combined_params = () + DataBase.params._gettuple()
        print(f"组合参数成功: {combined_params}")
        
        # 创建FeedBase实例
        feed = FeedBase()
        print(f"FeedBase创建成功")
        print(f"FeedBase.params._getitems(): {feed.params._getitems()}")
        
        print("✅ Feed兼容性测试通过!")
        
    except Exception as e:
        print(f"❌ Feed兼容性测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    test_feed_compatibility()