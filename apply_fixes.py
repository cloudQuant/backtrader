#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
这个脚本将修复应用到backtrader的LineSeries.__setattr__方法
"""

import os
import sys
import shutil
from datetime import datetime

# 定义修复内容
FIXED_SETATTR = """    # CRITICAL FIX: Add to lineiterators if not already there - 避免使用 'in' 操作符
            if safe_hasattr(self, '_lineiterators') and safe_hasattr(value, '_ltype'):
                try:
                    ltype = getattr(value, '_ltype', 0)
                    
                    # 关键修复：不使用 'in' 操作符，而是通过ID比较来检查是否已存在
                    found = False
                    for item in self._lineiterators[ltype]:
                        if id(item) == id(value):
                            found = True
                            break
                            
                    if not found:
                        self._lineiterators[ltype].append(value)
                except Exception:
                    pass"""

ORIGINAL_PATTERN = """            # CRITICAL FIX: Add to lineiterators if not already there
            if safe_hasattr(self, '_lineiterators') and safe_hasattr(value, '_ltype'):
                try:
                    ltype = getattr(value, '_ltype', 0)
                    if value not in self._lineiterators[ltype]:
                        self._lineiterators[ltype].append(value)
                except Exception:
                    pass"""

def apply_fix():
    """应用修复到LineSeries.__setattr__方法"""
    # 检查用户安装的backtrader
    import backtrader
    bt_path = os.path.dirname(backtrader.__file__)
    lineseries_path = os.path.join(bt_path, 'lineseries.py')
    
    # 首先创建备份
    backup_path = lineseries_path + '.backup.' + datetime.now().strftime('%Y%m%d%H%M%S')
    print(f"创建备份: {backup_path}")
    shutil.copy2(lineseries_path, backup_path)
    
    # 读取原始文件
    with open(lineseries_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 应用修复
    if ORIGINAL_PATTERN in content:
        fixed_content = content.replace(ORIGINAL_PATTERN, FIXED_SETATTR)
        with open(lineseries_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        print(f"修复成功应用到 {lineseries_path}")
    else:
        print("未找到匹配的代码模式，请手动应用修复")
        print("请在LineSeries.__setattr__方法中查找'if value not in self._lineiterators[ltype]'")
        print("将其替换为ID比较的实现")
        
    print("\n修复说明:")
    print("1. 问题: 在检查indicator是否已存在于self._lineiterators列表时，")
    print("   使用'in'运算符会触发对象的__eq__方法，导致无限递归")
    print("2. 解决方案: 使用对象ID比较而不是'in'运算符来检查列表成员")
    print("3. 对于运行中的错误，请重新启动Python环境使修复生效")

if __name__ == "__main__":
    apply_fix()
