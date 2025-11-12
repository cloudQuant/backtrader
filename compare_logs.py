#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
对比master分支和remove-metaprogramming分支的交易日志
找出所有差异点
"""

import re
from pathlib import Path

def parse_log_line(line):
    """解析日志行，提取关键信息"""
    # 提取日期
    date_match = re.match(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', line)
    if not date_match:
        return None
    
    date = date_match.group(1)
    content = line[len(date)+2:]  # Skip date and ", "
    
    return {
        'date': date,
        'content': content,
        'line': line
    }

def extract_trades(log_file):
    """从日志文件中提取交易记录"""
    trades = []
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            parsed = parse_log_line(line)
            if parsed:
                trades.append(parsed)
    
    return trades

def compare_logs(master_log, remove_meta_log):
    """对比两个日志文件"""
    print("=" * 80)
    print("日志对比分析")
    print("=" * 80)
    
    master_trades = extract_trades(master_log)
    remove_meta_trades = extract_trades(remove_meta_log)
    
    print(f"\nMaster分支日志行数: {len(master_trades)}")
    print(f"Remove-metaprogramming分支日志行数: {len(remove_meta_trades)}")
    
    # 找出第一个不同的地方
    print("\n" + "=" * 80)
    print("查找第一个差异点")
    print("=" * 80)
    
    min_len = min(len(master_trades), len(remove_meta_trades))
    first_diff_idx = None
    
    for i in range(min_len):
        if master_trades[i]['line'] != remove_meta_trades[i]['line']:
            first_diff_idx = i
            break
    
    if first_diff_idx is not None:
        print(f"\n第一个差异出现在第 {first_diff_idx + 1} 行")
        print(f"\n前后10行对比:")
        
        start = max(0, first_diff_idx - 5)
        end = min(min_len, first_diff_idx + 5)
        
        print("\n--- Master分支 ---")
        for i in range(start, end):
            prefix = ">>>" if i == first_diff_idx else "   "
            print(f"{prefix} {i+1:4d}: {master_trades[i]['line']}")
        
        print("\n--- Remove-metaprogramming分支 ---")
        for i in range(start, end):
            prefix = ">>>" if i == first_diff_idx else "   "
            print(f"{prefix} {i+1:4d}: {remove_meta_trades[i]['line']}")
        
        # 继续找后续的差异
        print("\n" + "=" * 80)
        print("后续差异统计")
        print("=" * 80)
        
        diff_count = 0
        diff_dates = set()
        for i in range(first_diff_idx, min_len):
            if master_trades[i]['line'] != remove_meta_trades[i]['line']:
                diff_count += 1
                diff_dates.add(master_trades[i]['date'])
        
        print(f"\n从第一个差异点到日志结束，共有 {diff_count} 行不同")
        print(f"涉及的交易日期数: {len(diff_dates)}")
        
        # 显示涉及的日期
        if diff_dates:
            sorted_dates = sorted(list(diff_dates))[:20]  # 只显示前20个
            print(f"\n受影响的日期（前20个）:")
            for date in sorted_dates:
                print(f"  - {date}")
    else:
        print("\n前 {} 行完全一致".format(min_len))
        if len(master_trades) != len(remove_meta_trades):
            print(f"但总行数不同: master={len(master_trades)}, remove-meta={len(remove_meta_trades)}")
    
    # 统计最终结果差异
    print("\n" + "=" * 80)
    print("最终结果对比")
    print("=" * 80)
    
    # 查找最后几行的结果
    master_last_lines = [t['line'] for t in master_trades[-10:]]
    remove_meta_last_lines = [t['line'] for t in remove_meta_trades[-10:]]
    
    print("\nMaster分支最后10行:")
    for line in master_last_lines:
        print(f"  {line}")
    
    print("\nRemove-metaprogramming分支最后10行:")
    for line in remove_meta_last_lines:
        print(f"  {line}")

if __name__ == "__main__":
    log_dir = Path(__file__).parent / "logs"
    
    master_log = 'logs/test_02_multi_extend_data_master_20251106_185413.log'
    remove_meta_log = 'logs/test_after_fix_v2.log'
    
    if not Path(master_log).exists():
        print(f"Error: {master_log} 不存在")
        exit(1)
    
    if not Path(remove_meta_log).exists():
        print(f"Error: {remove_meta_log} 不存在")
        exit(1)
    
    compare_logs(master_log, remove_meta_log)
