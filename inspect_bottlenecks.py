#!/usr/bin/env python3
"""
性能瓶颈代码检查工具
快速查看性能瓶颈函数的具体实现
"""

import os
import re
from pathlib import Path


def show_function_code(filepath: str, lineno: int, funcname: str, context_lines: int = 10):
    """显示函数代码及其上下文"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 转换为0-based索引
        start_idx = max(0, lineno - 1 - context_lines)
        end_idx = min(len(lines), lineno + context_lines)
        
        print(f"\n{'='*100}")
        print(f"文件: {filepath}")
        print(f"函数: {funcname} (第 {lineno} 行)")
        print(f"{'='*100}\n")
        
        for i in range(start_idx, end_idx):
            line_num = i + 1
            marker = ">>> " if line_num == lineno else "    "
            print(f"{marker}{line_num:4d} | {lines[i].rstrip()}")
        
        print()
        
    except FileNotFoundError:
        print(f"错误: 文件不存在 - {filepath}")
    except Exception as e:
        print(f"错误: {e}")


def main():
    """主函数 - 检查所有关键的性能瓶颈"""
    
    print("=" * 100)
    print("BACKTRADER 性能瓶颈代码检查")
    print("=" * 100)
    print()
    print("正在检查 Top 5 性能瓶颈函数的代码实现...")
    print()
    
    # Top 5 性能瓶颈
    bottlenecks = [
        ("backtrader/linebuffer.py", 198, "__len__", "1.105秒 (489,324次调用)"),
        ("backtrader/lineseries.py", 968, "__len__", "0.417秒 (69,876次调用)"),
        ("backtrader/linebuffer.py", 300, "__getitem__", "0.353秒 (228,292次调用)"),
        ("backtrader/lineseries.py", 781, "__getattr__", "0.275秒 (106,440次调用)"),
        ("backtrader/lineseries.py", 879, "__setattr__", "0.210秒 (171,298次调用)"),
        ("backtrader/metabase.py", 1332, "_initialize_indicator_aliases", "0.199秒 (149次调用)"),
    ]
    
    for i, (filepath, lineno, funcname, stats) in enumerate(bottlenecks, 1):
        print(f"\n🔴 瓶颈 #{i}: {funcname} - {stats}")
        show_function_code(filepath, lineno, funcname, context_lines=15)
    
    # 对比检查 - 看看 Master 版本中的快速实现
    print("\n" + "=" * 100)
    print("对比: Master 版本中的高效实现")
    print("=" * 100)
    
    # 检查旧的 __getitem__ 实现（如果存在）
    print("\n📌 检查: linebuffer.py 中是否还保留了旧的 __getitem__ 实现 (162行)")
    show_function_code("backtrader/linebuffer.py", 162, "__getitem__", context_lines=15)
    
    # 生成优化建议
    print("\n" + "=" * 100)
    print("优化建议总结")
    print("=" * 100)
    print()
    print("1. linebuffer.py:198(__len__)")
    print("   - 添加缓存机制，避免重复计算")
    print("   - 检查是否有不必要的属性访问或循环")
    print()
    print("2. lineseries.py:968(__len__)")
    print("   - 检查是否调用了 linebuffer.__len__")
    print("   - 考虑使用懒计算")
    print()
    print("3. linebuffer.py:300(__getitem__)")
    print("   - 对比第162行的实现，找出差异")
    print("   - 恢复快速路径（减少类型检查）")
    print()
    print("4. lineseries.py:781(__getattr__)")
    print("   - 添加属性缓存")
    print("   - 考虑使用 __slots__")
    print()
    print("5. lineseries.py:879(__setattr__)")
    print("   - 减少不必要的拦截")
    print("   - 直接设置常用属性")
    print()
    print("6. metabase.py:1332(_initialize_indicator_aliases)")
    print("   - 检查是否可以在类定义时执行")
    print("   - 添加缓存避免重复初始化")
    print()


if __name__ == "__main__":
    main()

