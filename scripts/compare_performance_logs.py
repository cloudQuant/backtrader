#!/usr/bin/env python
"""Compare two performance profiling logs and generate a detailed report.

Usage:
    python scripts/compare_performance_logs.py <baseline_log> <current_log>

Example:
    python scripts/compare_performance_logs.py \
        logs/performance_profile_development_20260117_093551.log \
        logs/performance_profile_development_20260117_101015.log
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path


def parse_log_file(filepath: str) -> dict:
    """Parse a performance log file and extract function statistics.
    
    Returns:
        dict with keys:
            - 'total_time': float, total execution time
            - 'functions': dict mapping function_name to {ncalls, tottime, cumtime}
    """
    result = {
        'total_time': 0.0,
        'functions': {},
        'strategies_count': 0,
        'successful': 0,
        'failed': 0,
    }
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract total execution time
    time_match = re.search(r'Total Execution Time:\s*([\d.]+)\s*seconds', content)
    if time_match:
        result['total_time'] = float(time_match.group(1))
    
    # Extract aggregate execution time (if available)
    agg_match = re.search(r'Aggregate execution time:\s*([\d.]+)\s*seconds', content)
    if agg_match:
        result['aggregate_time'] = float(agg_match.group(1))
    
    # Extract strategy counts
    strat_match = re.search(r'Total Strategies Tested:\s*(\d+)', content)
    if strat_match:
        result['strategies_count'] = int(strat_match.group(1))
    
    success_match = re.search(r'Successful:\s*(\d+)', content)
    if success_match:
        result['successful'] = int(success_match.group(1))
    
    # Parse function statistics from SECTION 1 and SECTION 2
    # Format: ncalls  tottime  per call  cumtime  per call  function
    # Example: 21,269,149    24.292190     0.000001    27.642500     0.000001  ...lineseries.py:1344(__setattr__)
    
    func_pattern = re.compile(
        r'^\s*([\d,]+)\s+'        # ncalls (with commas)
        r'([\d.]+)\s+'            # tottime
        r'[\d.]+\s+'              # per call (ignored)
        r'([\d.]+)\s+'            # cumtime
        r'[\d.]+\s+'              # per call (ignored)
        r'(.+)$',                 # function name
        re.MULTILINE
    )
    
    for match in func_pattern.finditer(content):
        ncalls_str = match.group(1).replace(',', '')
        ncalls = int(ncalls_str)
        tottime = float(match.group(2))
        cumtime = float(match.group(3))
        func_name = match.group(4).strip()
        
        # Normalize function name - extract just the file:line(func) part
        # Handle patterns like: ...path/to/file.py:123(funcname)
        func_short = func_name
        if '(' in func_name:
            # Extract file.py:line(func) pattern
            parts = func_name.split('/')
            if parts:
                func_short = parts[-1] if '(' in parts[-1] else func_name
        
        # Use full function name as key but store short version too
        if func_name not in result['functions']:
            result['functions'][func_name] = {
                'ncalls': ncalls,
                'tottime': tottime,
                'cumtime': cumtime,
                'short_name': func_short,
            }
        else:
            # Aggregate if same function appears multiple times
            result['functions'][func_name]['ncalls'] += ncalls
            result['functions'][func_name]['tottime'] += tottime
            result['functions'][func_name]['cumtime'] = max(
                result['functions'][func_name]['cumtime'], cumtime
            )
    
    return result


def normalize_func_key(func_name: str) -> str:
    """Normalize function name for comparison across logs."""
    # Extract the core pattern: filename.py:line(funcname)
    # Handle: ...path/file.py:123(func)
    if '(' in func_name:
        # Find the last part after /
        parts = func_name.split('/')
        for part in reversed(parts):
            if '(' in part and '.py:' in part:
                return part
            if '(' in part and ':0(' in part:
                # Built-in functions like ~:0(<built-in method builtins.len>)
                return part
    return func_name


def compare_logs(baseline: dict, current: dict) -> dict:
    """Compare two parsed log results."""
    comparison = {
        'time_change': current.get('total_time', 0) - baseline.get('total_time', 0),
        'time_pct_change': 0.0,
        'aggregate_change': 0.0,
        'functions_reduced': [],  # [(name, old_calls, new_calls, reduction_pct)]
        'functions_increased': [],
        'functions_removed': [],  # In baseline but not in current
        'functions_added': [],    # In current but not in baseline
        'top_improvements': [],
        'top_regressions': [],
    }
    
    if baseline.get('total_time', 0) > 0:
        comparison['time_pct_change'] = (
            comparison['time_change'] / baseline['total_time'] * 100
        )
    
    if baseline.get('aggregate_time', 0) > 0 and current.get('aggregate_time', 0) > 0:
        comparison['aggregate_change'] = (
            current['aggregate_time'] - baseline['aggregate_time']
        )
    
    # Normalize function names for comparison
    baseline_normalized = {}
    for name, data in baseline['functions'].items():
        key = normalize_func_key(name)
        if key not in baseline_normalized:
            baseline_normalized[key] = data.copy()
            baseline_normalized[key]['original_name'] = name
        else:
            baseline_normalized[key]['ncalls'] += data['ncalls']
    
    current_normalized = {}
    for name, data in current['functions'].items():
        key = normalize_func_key(name)
        if key not in current_normalized:
            current_normalized[key] = data.copy()
            current_normalized[key]['original_name'] = name
        else:
            current_normalized[key]['ncalls'] += data['ncalls']
    
    # Find changes
    all_keys = set(baseline_normalized.keys()) | set(current_normalized.keys())
    
    for key in all_keys:
        old_data = baseline_normalized.get(key)
        new_data = current_normalized.get(key)
        
        if old_data and new_data:
            old_calls = old_data['ncalls']
            new_calls = new_data['ncalls']
            
            if old_calls > 0:
                change_pct = (new_calls - old_calls) / old_calls * 100
            else:
                change_pct = 100.0 if new_calls > 0 else 0.0
            
            call_diff = new_calls - old_calls
            
            # Time changes
            old_tottime = old_data['tottime']
            new_tottime = new_data['tottime']
            time_diff = new_tottime - old_tottime
            
            entry = {
                'name': key,
                'short_name': new_data.get('short_name', key),
                'old_calls': old_calls,
                'new_calls': new_calls,
                'call_diff': call_diff,
                'change_pct': change_pct,
                'old_tottime': old_tottime,
                'new_tottime': new_tottime,
                'time_diff': time_diff,
            }
            
            if call_diff < 0:
                comparison['functions_reduced'].append(entry)
            elif call_diff > 0:
                comparison['functions_increased'].append(entry)
        
        elif old_data and not new_data:
            comparison['functions_removed'].append({
                'name': key,
                'old_calls': old_data['ncalls'],
                'old_tottime': old_data['tottime'],
            })
        
        elif new_data and not old_data:
            comparison['functions_added'].append({
                'name': key,
                'new_calls': new_data['ncalls'],
                'new_tottime': new_data['tottime'],
            })
    
    # Sort by impact
    comparison['functions_reduced'].sort(key=lambda x: x['call_diff'])
    comparison['functions_increased'].sort(key=lambda x: -x['call_diff'])
    
    # Top improvements (most calls reduced)
    comparison['top_improvements'] = comparison['functions_reduced'][:20]
    
    # Top regressions (most calls increased)
    comparison['top_regressions'] = comparison['functions_increased'][:20]
    
    return comparison


def format_number(n: int) -> str:
    """Format number with commas."""
    return f"{n:,}"


def format_pct(pct: float) -> str:
    """Format percentage with sign."""
    if pct >= 0:
        return f"+{pct:.1f}%"
    return f"{pct:.1f}%"


def generate_report(baseline_path: str, current_path: str, baseline: dict, 
                   current: dict, comparison: dict) -> str:
    """Generate a detailed comparison report."""
    lines = []
    
    lines.append("=" * 80)
    lines.append("性能日志对比报告 / Performance Log Comparison Report")
    lines.append("=" * 80)
    lines.append("")
    
    lines.append("## 文件信息")
    lines.append(f"- **基准日志 (Baseline)**: {baseline_path}")
    lines.append(f"- **当前日志 (Current)**: {current_path}")
    lines.append("")
    
    # Overall summary
    lines.append("## 整体性能对比")
    lines.append("")
    lines.append("| 指标 | 基准值 | 当前值 | 变化 |")
    lines.append("|------|--------|--------|------|")
    
    baseline_time = baseline.get('total_time', 0)
    current_time = current.get('total_time', 0)
    time_diff = current_time - baseline_time
    time_pct = (time_diff / baseline_time * 100) if baseline_time > 0 else 0
    
    time_indicator = "✅ 改善" if time_diff < 0 else ("⚠️ 增加" if time_diff > 0 else "➡️ 持平")
    lines.append(f"| 总执行时间 | {baseline_time:.2f}s | {current_time:.2f}s | {time_diff:+.2f}s ({format_pct(time_pct)}) {time_indicator} |")
    
    if baseline.get('aggregate_time') and current.get('aggregate_time'):
        agg_base = baseline['aggregate_time']
        agg_curr = current['aggregate_time']
        agg_diff = agg_curr - agg_base
        agg_pct = (agg_diff / agg_base * 100) if agg_base > 0 else 0
        agg_indicator = "✅" if agg_diff < 0 else "⚠️"
        lines.append(f"| 聚合执行时间 | {agg_base:.2f}s | {agg_curr:.2f}s | {agg_diff:+.2f}s ({format_pct(agg_pct)}) {agg_indicator} |")
    
    lines.append(f"| 策略数量 | {baseline.get('strategies_count', 0)} | {current.get('strategies_count', 0)} | - |")
    lines.append(f"| 成功数量 | {baseline.get('successful', 0)} | {current.get('successful', 0)} | - |")
    lines.append("")
    
    # Functions with reduced calls
    lines.append("## 函数调用次数减少 (优化效果) 🎉")
    lines.append("")
    
    if comparison['functions_reduced']:
        lines.append("| 函数 | 基准调用次数 | 当前调用次数 | 减少量 | 减少比例 | 时间变化 |")
        lines.append("|------|-------------|-------------|--------|---------|---------|")
        
        for entry in comparison['top_improvements'][:30]:
            name = entry['short_name'][:50]
            old_calls = format_number(entry['old_calls'])
            new_calls = format_number(entry['new_calls'])
            diff = format_number(abs(entry['call_diff']))
            pct = f"{entry['change_pct']:.1f}%"
            time_diff = f"{entry['time_diff']:+.2f}s"
            lines.append(f"| `{name}` | {old_calls} | {new_calls} | -{diff} | {pct} | {time_diff} |")
    else:
        lines.append("*无函数调用次数减少*")
    lines.append("")
    
    # Functions with increased calls
    lines.append("## 函数调用次数增加 (需关注) ⚠️")
    lines.append("")
    
    if comparison['functions_increased']:
        lines.append("| 函数 | 基准调用次数 | 当前调用次数 | 增加量 | 增加比例 | 时间变化 |")
        lines.append("|------|-------------|-------------|--------|---------|---------|")
        
        for entry in comparison['top_regressions'][:20]:
            name = entry['short_name'][:50]
            old_calls = format_number(entry['old_calls'])
            new_calls = format_number(entry['new_calls'])
            diff = format_number(entry['call_diff'])
            pct = f"+{entry['change_pct']:.1f}%"
            time_diff = f"{entry['time_diff']:+.2f}s"
            lines.append(f"| `{name}` | {old_calls} | {new_calls} | +{diff} | {pct} | {time_diff} |")
    else:
        lines.append("*无函数调用次数增加*")
    lines.append("")
    
    # Key builtin functions comparison
    lines.append("## 内置函数调用对比")
    lines.append("")
    
    builtin_funcs = ['builtins.len', 'builtins.isinstance', 'builtins.hasattr', 
                     'builtins.getattr', 'builtins.setattr']
    
    lines.append("| 内置函数 | 基准调用次数 | 当前调用次数 | 变化 |")
    lines.append("|----------|-------------|-------------|------|")
    
    for builtin in builtin_funcs:
        old_entry = None
        new_entry = None
        
        for entry in comparison['functions_reduced'] + comparison['functions_increased']:
            if builtin in entry['name']:
                if entry in comparison['functions_reduced']:
                    old_entry = entry
                else:
                    new_entry = entry
                break
        
        # Search in all functions
        for key, data in baseline['functions'].items():
            if builtin in key:
                old_calls = data['ncalls']
                break
        else:
            old_calls = 0
        
        for key, data in current['functions'].items():
            if builtin in key:
                new_calls = data['ncalls']
                break
        else:
            new_calls = 0
        
        if old_calls > 0 or new_calls > 0:
            diff = new_calls - old_calls
            pct = (diff / old_calls * 100) if old_calls > 0 else 0
            indicator = "✅" if diff < 0 else ("⚠️" if diff > 0 else "➡️")
            lines.append(f"| `{builtin}` | {format_number(old_calls)} | {format_number(new_calls)} | {format_number(diff)} ({format_pct(pct)}) {indicator} |")
    
    lines.append("")
    
    # Summary statistics
    lines.append("## 统计摘要")
    lines.append("")
    lines.append(f"- **调用次数减少的函数**: {len(comparison['functions_reduced'])} 个")
    lines.append(f"- **调用次数增加的函数**: {len(comparison['functions_increased'])} 个")
    lines.append(f"- **新增的函数**: {len(comparison['functions_added'])} 个")
    lines.append(f"- **移除的函数**: {len(comparison['functions_removed'])} 个")
    lines.append("")
    
    # Total call reduction
    total_reduced = sum(abs(e['call_diff']) for e in comparison['functions_reduced'])
    total_increased = sum(e['call_diff'] for e in comparison['functions_increased'])
    net_change = total_increased - total_reduced
    
    lines.append(f"- **总调用次数减少**: {format_number(total_reduced)}")
    lines.append(f"- **总调用次数增加**: {format_number(total_increased)}")
    lines.append(f"- **净变化**: {format_number(net_change)}")
    lines.append("")
    
    lines.append("=" * 80)
    lines.append("报告生成完毕")
    lines.append("=" * 80)
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Compare two performance profiling logs'
    )
    parser.add_argument(
        'baseline', 
        help='Path to baseline (old) performance log'
    )
    parser.add_argument(
        'current', 
        help='Path to current (new) performance log'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output file for the report (optional, defaults to stdout)'
    )
    
    args = parser.parse_args()
    
    # Validate files exist
    if not Path(args.baseline).exists():
        print(f"Error: Baseline file not found: {args.baseline}", file=sys.stderr)
        sys.exit(1)
    
    if not Path(args.current).exists():
        print(f"Error: Current file not found: {args.current}", file=sys.stderr)
        sys.exit(1)
    
    # Parse logs
    print(f"Parsing baseline: {args.baseline}")
    baseline = parse_log_file(args.baseline)
    print(f"  - Found {len(baseline['functions'])} functions")
    
    print(f"Parsing current: {args.current}")
    current = parse_log_file(args.current)
    print(f"  - Found {len(current['functions'])} functions")
    
    # Compare
    print("Comparing logs...")
    comparison = compare_logs(baseline, current)
    
    # Generate report
    report = generate_report(args.baseline, args.current, baseline, current, comparison)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"\nReport saved to: {args.output}")
    else:
        print("\n" + report)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
