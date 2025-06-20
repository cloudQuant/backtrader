#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

"""调试MomentumNew的方法解析"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backtrader'))

from backtrader.indicators.momentum import MomentumNew


def debug_momentum_methods():
    print("调试MomentumNew的方法...")
    
    # 检查类的MRO
    print(f"MRO: {MomentumNew.__mro__}")
    
    # 检查类的属性
    print(f"类属性: {dir(MomentumNew)}")
    
    # 检查特定方法
    methods_to_check = ['_gettuple', '_getitems', '_getpairs', 'params']
    for method in methods_to_check:
        print(f"{method}: {hasattr(MomentumNew, method)}")
        if hasattr(MomentumNew, method):
            print(f"  类型: {type(getattr(MomentumNew, method))}")
    
    # 检查兼容mixin
    from backtrader.parameters import MetaParamsCompatibilityMixin
    print(f"MomentumNew是否是MetaParamsCompatibilityMixin的实例: {isinstance(MomentumNew(), MetaParamsCompatibilityMixin)}")
    print(f"MetaParamsCompatibilityMixin方法: {dir(MetaParamsCompatibilityMixin)}")


if __name__ == '__main__':
    debug_momentum_methods()