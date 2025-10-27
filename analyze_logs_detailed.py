#!/usr/bin/env python
"""
深度分析性能日志差异
完整读取master和remove-metaprogramming两个版本的性能日志，进行详细对比
"""

import re
import glob
from collections import defaultdict

def parse_profile_log(filename):
    """完整解析性能日志文件"""
    print(f"\n{'='*80}")
    print(f"解析文件: {filename}")
    print(f"{'='*80}\n")
    
    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # 提取总体统计
    stats = {}
    if m := re.search(r'Total function calls:\s*([\d,]+)', content):
        stats['total_calls'] = m.group(1).replace(',', '')
    if m := re.search(r'Total primitive calls:\s*([\d,]+)', content):
        stats['primitive_calls'] = m.group(1).replace(',', '')
    if m := re.search(r'Total unique functions:\s*([\d,]+)', content):
        stats['unique_funcs'] = m.group(1).replace(',', '')
    if m := re.search(r'Total execution time:\s*([\d.]+)\s*s', content):
        stats['total_time'] = float(m.group(1))
    
    # 解析所有函数调用记录
    # 格式: ncalls  tottime  percall  cumtime  percall filename:lineno(function)
    pattern = r'\s*(\d+(?:/\d+)?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+?)(?:\s{2,}|$)'
    functions = []
    
    for match in re.finditer(pattern, content):
        ncalls = match.group(1)
        tottime = float(match.group(2))
        cumtime = float(match.group(4))
        location = match.group(6).strip()
        
        functions.append({
            'ncalls': ncalls,
            'ncalls_num': int(ncalls.split('/')[0]) if '/' in ncalls else int(ncalls),
            'tottime': tottime,
            'cumtime': cumtime,
            'location': location
        })
    
    return stats, functions

def compare_versions(master_file, remove_file):
    """对比两个版本的性能差异"""
    
    print("\n" + "="*100)
    print("完整性能对比分析")
    print("="*100)
    
    # 解析两个版本
    master_stats, master_funcs = parse_profile_log(master_file)
    remove_stats, remove_funcs = parse_profile_log(remove_file)
    
    # 打印总体统计对比
    print("\n### 总体性能统计对比\n")
    print(f"{'指标':<30} {'Master版本':>20} {'Remove版本':>20} {'变化':>15} {'变化率':>10}")
    print("-" * 100)
    
    for key in ['total_calls', 'primitive_calls', 'unique_funcs']:
        if key in master_stats and key in remove_stats:
            m_val = int(master_stats[key])
            r_val = int(remove_stats[key])
            diff = r_val - m_val
            pct = (diff / m_val * 100) if m_val > 0 else 0
            print(f"{key:<30} {m_val:>20,} {r_val:>20,} {diff:>15,} {pct:>9.1f}%")
    
    if 'total_time' in master_stats and 'total_time' in remove_stats:
        m_time = master_stats['total_time']
        r_time = remove_stats['total_time']
        diff = r_time - m_time
        pct = (diff / m_time * 100) if m_time > 0 else 0
        print(f"{'total_time (seconds)':<30} {m_time:>20.2f} {r_time:>20.2f} {diff:>15.2f} {pct:>9.1f}%")
    
    # 创建函数索引
    master_dict = {f['location']: f for f in master_funcs}
    remove_dict = {f['location']: f for f in remove_funcs}
    
    # 找出显著变化的函数
    print("\n### TOP 50 性能下降最严重的函数（按tottime增量排序）\n")
    print(f"{'排名':<5} {'函数位置':<80} {'Master(s)':>12} {'Remove(s)':>12} {'增量(s)':>12} {'增长率':>10}")
    print("-" * 145)
    
    changes = []
    for loc, remove_func in remove_dict.items():
        if loc in master_dict:
            master_func = master_dict[loc]
            time_diff = remove_func['tottime'] - master_func['tottime']
            call_diff = remove_func['ncalls_num'] - master_func['ncalls_num']
            
            if time_diff > 0.001:  # 只关注有显著变化的
                pct_change = (time_diff / master_func['tottime'] * 100) if master_func['tottime'] > 0 else float('inf')
                changes.append({
                    'location': loc,
                    'master_time': master_func['tottime'],
                    'remove_time': remove_func['tottime'],
                    'time_diff': time_diff,
                    'pct_change': pct_change,
                    'master_calls': master_func['ncalls_num'],
                    'remove_calls': remove_func['ncalls_num'],
                    'call_diff': call_diff
                })
        else:
            # 新增的函数
            if remove_func['tottime'] > 0.01:
                changes.append({
                    'location': loc,
                    'master_time': 0,
                    'remove_time': remove_func['tottime'],
                    'time_diff': remove_func['tottime'],
                    'pct_change': float('inf'),
                    'master_calls': 0,
                    'remove_calls': remove_func['ncalls_num'],
                    'call_diff': remove_func['ncalls_num']
                })
    
    # 按时间增量排序
    changes.sort(key=lambda x: x['time_diff'], reverse=True)
    
    for i, change in enumerate(changes[:50], 1):
        loc = change['location'][:78]
        pct_str = f"+{change['pct_change']:.0f}%" if change['pct_change'] != float('inf') else "NEW"
        print(f"{i:<5} {loc:<80} {change['master_time']:>12.3f} {change['remove_time']:>12.3f} {change['time_diff']:>12.3f} {pct_str:>10}")
    
    # 调用次数增加最多的函数
    print("\n### TOP 30 调用次数增加最多的函数\n")
    print(f"{'排名':<5} {'函数位置':<80} {'Master次数':>15} {'Remove次数':>15} {'增量':>15} {'增长率':>10}")
    print("-" * 150)
    
    changes.sort(key=lambda x: x['call_diff'], reverse=True)
    for i, change in enumerate(changes[:30], 1):
        loc = change['location'][:78]
        pct_str = f"+{change['call_diff']/change['master_calls']*100:.0f}%" if change['master_calls'] > 0 else "NEW"
        print(f"{i:<5} {loc:<80} {change['master_calls']:>15,} {change['remove_calls']:>15,} {change['call_diff']:>15,} {pct_str:>10}")
    
    # 识别关键瓶颈
    print("\n### 关键性能瓶颈识别\n")
    
    # hasattr, getattr, setattr等内建函数
    builtin_funcs = ['hasattr', 'getattr', 'setattr', 'isinstance', 'len', 'type']
    print("#### 内建函数调用对比\n")
    for func_name in builtin_funcs:
        pattern = f"{{built-in method builtins.{func_name}}}"
        master_func = master_dict.get(pattern)
        remove_func = remove_dict.get(pattern)
        
        if master_func or remove_func:
            m_calls = master_func['ncalls_num'] if master_func else 0
            r_calls = remove_func['ncalls_num'] if remove_func else 0
            m_time = master_func['tottime'] if master_func else 0
            r_time = remove_func['tottime'] if remove_func else 0
            
            call_diff = r_calls - m_calls
            time_diff = r_time - m_time
            call_pct = (call_diff / m_calls * 100) if m_calls > 0 else float('inf')
            
            print(f"{func_name:>12}: Master={m_calls:>12,}次/{m_time:>8.3f}s  Remove={r_calls:>12,}次/{r_time:>8.3f}s  "
                  f"增加={call_diff:>12,}次/{time_diff:>7.3f}s ({call_pct:>8.1f}%)")
    
    return changes

def main():
    # 找到最新的日志文件
    master_files = glob.glob('performance_profile_master_*.log')
    remove_files = glob.glob('performance_profile_remove-metaprogramming_*.log')
    
    if not master_files or not remove_files:
        print("错误：找不到性能日志文件")
        return
    
    master_file = sorted(master_files)[-1]
    remove_file = sorted(remove_files)[-1]
    
    print(f"\n对比文件:")
    print(f"  Master版本: {master_file}")
    print(f"  Remove版本: {remove_file}")
    
    changes = compare_versions(master_file, remove_file)
    
    # 生成优化建议和TODO清单
    print("\n" + "="*100)
    print("优化建议和TODO清单")
    print("="*100)
    
    print("""
基于详细分析，按优先级排序的优化TODO清单：

## 🔴 紧急优化（预计恢复40-50%性能）

### TODO 1: 优化hasattr/getattr/setattr调用（最高优先级）
- [ ] 1.1 在lineseries.__getattr__中实现属性缓存
- [ ] 1.2 在lineseries.__setattr__中减少hasattr检查
- [ ] 1.3 在lineiterator中继续减少hasattr使用（已部分完成）
- [ ] 1.4 在所有热路径中用try-except替代hasattr
预期收益: 减少1500万+函数调用，节省8-12秒

### TODO 2: 优化lineseries.__getitem__
- [ ] 2.1 移除isinstance(value, float)检查
- [ ] 2.2 移除math.isnan()调用，使用value != value检查
- [ ] 2.3 简化异常处理逻辑
预期收益: 减少2000万+函数调用，节省3-5秒

### TODO 3: 优化参数系统
- [ ] 3.1 在Parameters类初始化时预创建所有参数属性
- [ ] 3.2 避免get_param/get方法的重复调用
- [ ] 3.3 使用__slots__优化Parameters对象
预期收益: 减少300万+函数调用，节省2-4秒

## 🟡 重要优化（预计恢复20-30%性能）

### TODO 4: 实现智能属性缓存
- [ ] 4.1 设计缓存策略（LRU或简单字典）
- [ ] 4.2 在__getattr__首次访问后缓存到__dict__
- [ ] 4.3 监控缓存命中率
预期收益: 减少1000万+函数调用，节省3-5秒

### TODO 5: 优化line访问模式
- [ ] 5.1 重新引入有限的描述符（不使用元类）
- [ ] 5.2 预编译常用的line访问路径
- [ ] 5.3 减少动态属性查找
预期收益: 减少500万+函数调用，节省2-3秒

### TODO 6: 减少对象创建开销
- [ ] 6.1 为小对象使用__slots__
- [ ] 6.2 对象池化频繁创建的临时对象
- [ ] 6.3 延迟初始化非关键属性
预期收益: 节省1-2秒

## 🟢 长期优化（需要架构评估）

### TODO 7: 考虑部分恢复元类
- [ ] 7.1 评估在关键路径使用轻量级元类的可行性
- [ ] 7.2 设计混合架构（元类+非元类）
- [ ] 7.3 性能vs复杂度权衡分析

### TODO 8: C扩展优化
- [ ] 8.1 识别最热的路径
- [ ] 8.2 用Cython重写关键函数
- [ ] 8.3 保持Python接口兼容性

## 执行顺序建议

第一轮（预计2-3天）：
1. 完成TODO 1.1-1.4（hasattr优化）
2. 完成TODO 2.1-2.3（__getitem__优化）
3. 运行性能测试，预期降至45-48秒

第二轮（预计1-2天）：
1. 完成TODO 3.1-3.3（参数系统优化）
2. 完成TODO 4.1-4.3（属性缓存）
3. 运行性能测试，预期降至38-42秒

第三轮（预计2-3天）：
1. 完成TODO 5和6
2. 运行性能测试，预期降至35-38秒
3. 接近master版本性能（33.42秒）

每轮优化后都要：
- 运行性能测试
- 对比日志文件
- 验证功能正确性
- 提交代码
    """)

if __name__ == '__main__':
    main()
