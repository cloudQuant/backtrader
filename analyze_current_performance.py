#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
分析当前性能日志，对比优化前后的状态
"""

import re
import sys
from collections import defaultdict

def parse_log_file(filename):
    """解析性能日志文件"""
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取总体信息
    total_calls_match = re.search(r'(\d+)\s+function calls.*in\s+([\d.]+)\s+seconds', content)
    if total_calls_match:
        total_calls = int(total_calls_match.group(1))
        total_time = float(total_calls_match.group(2))
    else:
        total_calls, total_time = 0, 0.0
    
    # 提取函数统计信息
    functions = []
    
    # 查找统计表格部分
    pattern = r'\s+(\d+(?:/\d+)?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([^:]+):(\d+)\(([^)]+)\)'
    
    for match in re.finditer(pattern, content):
        ncalls = match.group(1)
        tottime = float(match.group(2))
        percall_tot = float(match.group(3))
        cumtime = float(match.group(4))
        percall_cum = float(match.group(5))
        filename = match.group(6)
        lineno = match.group(7)
        funcname = match.group(8)
        
        # 解析ncalls (可能包含递归调用)
        if '/' in ncalls:
            calls, primitive = ncalls.split('/')
            ncalls_num = int(calls)
        else:
            ncalls_num = int(ncalls)
        
        functions.append({
            'ncalls': ncalls_num,
            'tottime': tottime,
            'cumtime': cumtime,
            'filename': filename,
            'lineno': lineno,
            'funcname': funcname,
            'fullname': f"{filename}:{lineno}({funcname})"
        })
    
    return {
        'total_calls': total_calls,
        'total_time': total_time,
        'functions': functions
    }

def analyze_bottlenecks(log_data):
    """分析性能瓶颈"""
    functions = log_data['functions']
    
    print("\n" + "="*100)
    print("当前性能瓶颈分析")
    print("="*100)
    print(f"\n总执行时间: {log_data['total_time']:.2f}秒")
    print(f"总函数调用: {log_data['total_calls']:,}次")
    print(f"平均每次调用: {(log_data['total_time']/log_data['total_calls']*1000000):.2f}微秒")
    
    # 按累计时间排序
    print("\n" + "-"*100)
    print("TOP 20 最耗时的函数 (按累计时间)")
    print("-"*100)
    print(f"{'排名':<5} {'函数':<60} {'调用次数':<15} {'累计时间':<12} {'占比':<8}")
    print("-"*100)
    
    sorted_by_cumtime = sorted(functions, key=lambda x: x['cumtime'], reverse=True)[:20]
    for i, func in enumerate(sorted_by_cumtime, 1):
        percent = (func['cumtime'] / log_data['total_time'] * 100)
        print(f"{i:<5} {func['funcname']:<60} {func['ncalls']:>14,} {func['cumtime']:>11.3f}s {percent:>7.1f}%")
    
    # 关键瓶颈函数分析
    print("\n" + "-"*100)
    print("关键瓶颈函数详细分析")
    print("-"*100)
    
    bottlenecks = {
        'hasattr': [],
        'getattr': [],
        'setattr': [],
        'isinstance': [],
        'isnan': [],
        '__getattr__': [],
        '__setattr__': [],
        '__getitem__': [],
        'forward': [],
    }
    
    for func in functions:
        funcname = func['funcname'].lower()
        for key in bottlenecks:
            if key in funcname:
                bottlenecks[key].append(func)
    
    for key, funcs in bottlenecks.items():
        if funcs:
            total_calls = sum(f['ncalls'] for f in funcs)
            total_time = sum(f['cumtime'] for f in funcs)
            print(f"\n{key.upper()}:")
            print(f"  总调用次数: {total_calls:,}")
            print(f"  总耗时: {total_time:.3f}秒 ({total_time/log_data['total_time']*100:.1f}%)")
            if funcs:
                print(f"  主要来源:")
                for f in sorted(funcs, key=lambda x: x['cumtime'], reverse=True)[:3]:
                    print(f"    - {f['fullname']}: {f['ncalls']:,}次, {f['cumtime']:.3f}秒")
    
    return bottlenecks

def compare_with_baseline(current_log, baseline_file):
    """与基准对比"""
    try:
        baseline_data = parse_log_file(baseline_file)
        
        print("\n" + "="*100)
        print(f"与基准对比: {baseline_file}")
        print("="*100)
        
        print(f"\n{'指标':<30} {'基准':<20} {'当前':<20} {'变化':<20}")
        print("-"*100)
        
        # 总执行时间对比
        time_diff = current_log['total_time'] - baseline_data['total_time']
        time_pct = (time_diff / baseline_data['total_time'] * 100) if baseline_data['total_time'] > 0 else 0
        print(f"{'总执行时间':<30} {baseline_data['total_time']:>19.2f}s {current_log['total_time']:>19.2f}s {time_diff:+19.2f}s ({time_pct:+.1f}%)")
        
        # 总调用次数对比
        calls_diff = current_log['total_calls'] - baseline_data['total_calls']
        calls_pct = (calls_diff / baseline_data['total_calls'] * 100) if baseline_data['total_calls'] > 0 else 0
        print(f"{'总函数调用':<30} {baseline_data['total_calls']:>19,} {current_log['total_calls']:>19,} {calls_diff:+19,} ({calls_pct:+.1f}%)")
        
        # 关键函数对比
        print("\n关键函数调用次数对比:")
        print(f"{'函数':<30} {'基准调用':<20} {'当前调用':<20} {'变化':<20}")
        print("-"*100)
        
        key_functions = ['hasattr', 'getattr', 'setattr', 'isinstance', '__getattr__', '__setattr__', '__getitem__']
        
        for key in key_functions:
            baseline_funcs = [f for f in baseline_data['functions'] if key in f['funcname'].lower()]
            current_funcs = [f for f in current_log['functions'] if key in f['funcname'].lower()]
            
            baseline_calls = sum(f['ncalls'] for f in baseline_funcs)
            current_calls = sum(f['ncalls'] for f in current_funcs)
            
            if baseline_calls > 0 or current_calls > 0:
                diff = current_calls - baseline_calls
                pct = (diff / baseline_calls * 100) if baseline_calls > 0 else float('inf')
                if pct == float('inf'):
                    print(f"{key:<30} {baseline_calls:>19,} {current_calls:>19,} {diff:+19,} (NEW)")
                else:
                    print(f"{key:<30} {baseline_calls:>19,} {current_calls:>19,} {diff:+19,} ({pct:+.1f}%)")
        
    except FileNotFoundError:
        print(f"\n警告: 找不到基准文件 {baseline_file}")
    except Exception as e:
        print(f"\n错误: 对比失败 - {e}")

def generate_optimization_recommendations(bottlenecks, log_data):
    """生成优化建议"""
    print("\n" + "="*100)
    print("优化建议 (按优先级)")
    print("="*100)
    
    recommendations = []
    
    # 分析hasattr
    if bottlenecks['hasattr']:
        total_calls = sum(f['ncalls'] for f in bottlenecks['hasattr'])
        total_time = sum(f['cumtime'] for f in bottlenecks['hasattr'])
        if total_calls > 5000000:  # 超过500万次
            recommendations.append({
                'priority': 1,
                'title': '优化 hasattr 调用',
                'issue': f'hasattr被调用{total_calls:,}次，耗时{total_time:.2f}秒',
                'solution': '使用 try-except (EAFP) 替代 hasattr (LBYL)',
                'expected_gain': f'减少{total_calls*0.7:,.0f}次调用，节省{total_time*0.7:.1f}秒',
                'files': ['backtrader/lineseries.py', 'backtrader/linebuffer.py', 'backtrader/lineiterator.py']
            })
    
    # 分析__getattr__
    if bottlenecks['__getattr__']:
        total_calls = sum(f['ncalls'] for f in bottlenecks['__getattr__'])
        total_time = sum(f['cumtime'] for f in bottlenecks['__getattr__'])
        if total_calls > 500000:
            recommendations.append({
                'priority': 1,
                'title': '实现 __getattr__ 属性缓存',
                'issue': f'__getattr__被调用{total_calls:,}次，耗时{total_time:.2f}秒',
                'solution': '首次访问后缓存属性到 __dict__，避免重复查找',
                'expected_gain': f'减少{total_calls*0.8:,.0f}次调用，节省{total_time*0.6:.1f}秒',
                'files': ['backtrader/lineseries.py']
            })
    
    # 分析__setattr__
    if bottlenecks['__setattr__']:
        total_calls = sum(f['ncalls'] for f in bottlenecks['__setattr__'])
        total_time = sum(f['cumtime'] for f in bottlenecks['__setattr__'])
        if total_calls > 1000000:
            recommendations.append({
                'priority': 2,
                'title': '优化 __setattr__ 性能',
                'issue': f'__setattr__被调用{total_calls:,}次，耗时{total_time:.2f}秒',
                'solution': '使用快速路径处理简单类型，减少内部的hasattr调用',
                'expected_gain': f'节省{total_time*0.5:.1f}秒',
                'files': ['backtrader/lineseries.py']
            })
    
    # 分析isinstance/isnan
    isinstance_calls = sum(f['ncalls'] for f in bottlenecks['isinstance'])
    isnan_calls = sum(f['ncalls'] for f in bottlenecks['isnan'])
    if isinstance_calls > 5000000 or isnan_calls > 2000000:
        isinstance_time = sum(f['cumtime'] for f in bottlenecks['isinstance'])
        isnan_time = sum(f['cumtime'] for f in bottlenecks['isnan'])
        recommendations.append({
            'priority': 2,
            'title': '优化 isinstance/isnan 检查',
            'issue': f'isinstance: {isinstance_calls:,}次, isnan: {isnan_calls:,}次',
            'solution': '使用 value != value 检测NaN (NaN的自比较特性)',
            'expected_gain': f'减少{(isinstance_calls+isnan_calls):,.0f}次调用，节省{isinstance_time+isnan_time:.1f}秒',
            'files': ['backtrader/lineseries.py', 'backtrader/linebuffer.py']
        })
    
    # 分析__getitem__
    if bottlenecks['__getitem__']:
        total_calls = sum(f['ncalls'] for f in bottlenecks['__getitem__'])
        total_time = sum(f['cumtime'] for f in bottlenecks['__getitem__'])
        if total_time > 3.0:
            recommendations.append({
                'priority': 2,
                'title': '优化 __getitem__ 方法',
                'issue': f'__getitem__被调用{total_calls:,}次，耗时{total_time:.2f}秒',
                'solution': '简化逻辑，减少类型检查，使用直接数组访问',
                'expected_gain': f'节省{total_time*0.5:.1f}秒',
                'files': ['backtrader/lineseries.py', 'backtrader/linebuffer.py']
            })
    
    # 分析forward
    if bottlenecks['forward']:
        total_calls = sum(f['ncalls'] for f in bottlenecks['forward'])
        total_time = sum(f['cumtime'] for f in bottlenecks['forward'])
        if total_time > 5.0:
            recommendations.append({
                'priority': 3,
                'title': '优化 forward 方法',
                'issue': f'forward被调用{total_calls:,}次，耗时{total_time:.2f}秒',
                'solution': '减少NaN检查，优化数组操作',
                'expected_gain': f'节省{total_time*0.3:.1f}秒',
                'files': ['backtrader/linebuffer.py', 'backtrader/lineseries.py']
            })
    
    # 按优先级排序
    recommendations.sort(key=lambda x: x['priority'])
    
    # 打印建议
    for i, rec in enumerate(recommendations, 1):
        print(f"\n{'🔴' if rec['priority'] == 1 else '🟡' if rec['priority'] == 2 else '🟢'} 优化建议 #{i}: {rec['title']}")
        print(f"   优先级: {'高' if rec['priority'] == 1 else '中' if rec['priority'] == 2 else '低'}")
        print(f"   问题: {rec['issue']}")
        print(f"   方案: {rec['solution']}")
        print(f"   预期收益: {rec['expected_gain']}")
        print(f"   涉及文件: {', '.join(rec['files'])}")
    
    # 总预期收益
    print("\n" + "="*100)
    print("总预期优化效果")
    print("="*100)
    
    total_expected_time_save = 0
    for rec in recommendations:
        # 从 expected_gain 中提取秒数
        import re
        match = re.search(r'节省([\d.]+)秒', rec['expected_gain'])
        if match:
            total_expected_time_save += float(match.group(1))
    
    current_time = log_data['total_time']
    expected_time = current_time - total_expected_time_save
    improvement_pct = (total_expected_time_save / current_time * 100) if current_time > 0 else 0
    
    print(f"\n当前执行时间: {current_time:.2f}秒")
    print(f"预期节省时间: {total_expected_time_save:.2f}秒")
    print(f"优化后时间: {expected_time:.2f}秒")
    print(f"性能提升: {improvement_pct:.1f}%")
    
    return recommendations

def main():
    # 分析当前日志
    import glob
    log_files = glob.glob('performance_profile_remove-metaprogramming_*.log')
    if not log_files:
        print("错误: 找不到性能日志文件")
        return 1
    
    # 使用最新的日志文件
    current_log_file = sorted(log_files)[-1]
    print(f"分析日志文件: {current_log_file}")
    
    current_data = parse_log_file(current_log_file)
    bottlenecks = analyze_bottlenecks(current_data)
    
    # 与master基准对比
    master_log = 'performance_profile_master_20251026_230910.log'
    compare_with_baseline(current_data, master_log)
    
    # 生成优化建议
    recommendations = generate_optimization_recommendations(bottlenecks, current_data)
    
    # 保存报告
    report_file = '当前性能分析报告.md'
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"# 当前性能分析报告\n\n")
        f.write(f"## 基本信息\n\n")
        f.write(f"- 日志文件: {current_log_file}\n")
        f.write(f"- 总执行时间: {current_data['total_time']:.2f}秒\n")
        f.write(f"- 总函数调用: {current_data['total_calls']:,}次\n")
        f.write(f"- 分析时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write(f"## 优化建议\n\n")
        for i, rec in enumerate(recommendations, 1):
            f.write(f"### {i}. {rec['title']}\n\n")
            f.write(f"**优先级**: {'高 🔴' if rec['priority'] == 1 else '中 🟡' if rec['priority'] == 2 else '低 🟢'}\n\n")
            f.write(f"**问题**: {rec['issue']}\n\n")
            f.write(f"**方案**: {rec['solution']}\n\n")
            f.write(f"**预期收益**: {rec['expected_gain']}\n\n")
            f.write(f"**涉及文件**: {', '.join(rec['files'])}\n\n")
        
        f.write(f"\n## 详细数据\n\n")
        f.write(f"详见完整性能日志: {current_log_file}\n")
    
    print(f"\n报告已保存到: {report_file}")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())




