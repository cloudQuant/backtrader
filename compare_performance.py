#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Performance comparison script for backtrader profiling reports
Compares two performance profile log files and generates a diff report
"""

import re
import sys
import os
from datetime import datetime
from collections import defaultdict


def parse_log_header(log_file_path):
    """
    Parse the header of a log file to extract metadata
    
    Returns:
        dict: Header information including branch, commit, execution time
    """
    header = {}
    
    with open(log_file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if 'Git Branch:' in line:
                header['branch'] = line.split(':', 1)[1].strip()
            elif 'Git Commit:' in line:
                header['commit'] = line.split(':', 1)[1].strip()
            elif 'Total Execution Time:' in line:
                time_str = line.split(':', 1)[1].strip().split()[0]
                header['execution_time'] = float(time_str)
            elif 'Test File:' in line:
                header['test_file'] = line.split(':', 1)[1].strip()
            elif 'Report Generated:' in line:
                header['generated'] = line.split(':', 1)[1].strip()
            elif 'SECTION 1:' in line:
                break  # Stop after header
    
    return header


def parse_function_stats(log_file_path):
    """
    Parse function statistics from a performance log file
    
    Returns:
        dict: Function statistics {function_name: {calls, tottime, cumtime}}
    """
    stats = {}
    in_stats_section = False
    
    with open(log_file_path, 'r', encoding='utf-8') as f:
        for line in f:
            # Detect when we're in a stats section
            if 'ncalls' in line and 'tottime' in line and 'cumtime' in line:
                in_stats_section = True
                continue
            
            # Stop at next section
            if in_stats_section and (line.startswith('SECTION') or line.startswith('=')):
                in_stats_section = False
            
            # Parse stat lines
            if in_stats_section and line.strip():
                # Format: ncalls  tottime  percall  cumtime  percall filename:lineno(function)
                parts = line.strip().split()
                if len(parts) >= 6:
                    try:
                        ncalls = parts[0]
                        tottime = float(parts[1])
                        cumtime = float(parts[3])
                        
                        # Extract function name and file
                        func_info = ' '.join(parts[5:])
                        
                        # Store stats
                        if func_info not in stats:
                            stats[func_info] = {
                                'ncalls': ncalls,
                                'tottime': tottime,
                                'cumtime': cumtime
                            }
                    except (ValueError, IndexError):
                        continue
    
    return stats


def compare_stats(stats1, stats2, header1, header2):
    """
    Compare statistics from two log files
    
    Args:
        stats1: Statistics from first log file
        stats2: Statistics from second log file
        header1: Header from first log file
        header2: Header from second log file
    
    Returns:
        dict: Comparison results
    """
    results = {
        'overall': {
            'branch1': header1['branch'],
            'branch2': header2['branch'],
            'time1': header1['execution_time'],
            'time2': header2['execution_time'],
            'time_diff': header2['execution_time'] - header1['execution_time'],
            'time_diff_pct': ((header2['execution_time'] - header1['execution_time']) / 
                             header1['execution_time'] * 100)
        },
        'improved': [],  # Functions that got faster
        'degraded': [],  # Functions that got slower
        'new': [],       # Functions only in log2
        'removed': []    # Functions only in log1
    }
    
    # Compare common functions
    all_funcs = set(stats1.keys()) | set(stats2.keys())
    
    for func in all_funcs:
        if func in stats1 and func in stats2:
            s1 = stats1[func]
            s2 = stats2[func]
            
            cumtime_diff = s2['cumtime'] - s1['cumtime']
            cumtime_diff_pct = (cumtime_diff / s1['cumtime'] * 100) if s1['cumtime'] > 0 else 0
            
            diff_info = {
                'function': func,
                'cumtime1': s1['cumtime'],
                'cumtime2': s2['cumtime'],
                'cumtime_diff': cumtime_diff,
                'cumtime_diff_pct': cumtime_diff_pct,
                'tottime1': s1['tottime'],
                'tottime2': s2['tottime'],
                'tottime_diff': s2['tottime'] - s1['tottime'],
                'ncalls1': s1['ncalls'],
                'ncalls2': s2['ncalls']
            }
            
            if cumtime_diff < -0.001:  # Improved (faster)
                results['improved'].append(diff_info)
            elif cumtime_diff > 0.001:  # Degraded (slower)
                results['degraded'].append(diff_info)
        
        elif func in stats2:
            results['new'].append({
                'function': func,
                'cumtime': stats2[func]['cumtime'],
                'ncalls': stats2[func]['ncalls']
            })
        
        elif func in stats1:
            results['removed'].append({
                'function': func,
                'cumtime': stats1[func]['cumtime'],
                'ncalls': stats1[func]['ncalls']
            })
    
    # Sort by absolute difference
    results['improved'].sort(key=lambda x: abs(x['cumtime_diff']), reverse=True)
    results['degraded'].sort(key=lambda x: abs(x['cumtime_diff']), reverse=True)
    
    return results


def generate_comparison_report(results, output_file='performance_comparison.md'):
    """
    Generate a markdown report comparing two performance profiles
    
    Args:
        results: Comparison results from compare_stats()
        output_file: Output markdown file path
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Performance Comparison Report\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("=" * 100 + "\n\n")
        
        # Overall comparison
        f.write("## Overall Performance\n\n")
        overall = results['overall']
        f.write(f"| Metric | {overall['branch1']} | {overall['branch2']} | Difference |\n")
        f.write("|--------|----------|----------|------------|\n")
        f.write(f"| **Execution Time** | {overall['time1']:.4f}s | {overall['time2']:.4f}s | ")
        
        if overall['time_diff'] > 0:
            f.write(f"+{overall['time_diff']:.4f}s (+{overall['time_diff_pct']:.2f}%) ⚠️ **SLOWER** |\n\n")
        else:
            f.write(f"{overall['time_diff']:.4f}s ({overall['time_diff_pct']:.2f}%) ✅ **FASTER** |\n\n")
        
        # Summary
        f.write("### Summary\n\n")
        f.write(f"- Functions improved (faster): **{len(results['improved'])}**\n")
        f.write(f"- Functions degraded (slower): **{len(results['degraded'])}**\n")
        f.write(f"- New functions: **{len(results['new'])}**\n")
        f.write(f"- Removed functions: **{len(results['removed'])}**\n\n")
        
        # Top degraded functions
        if results['degraded']:
            f.write("## Top 20 Degraded Functions (Slower)\n\n")
            f.write("Functions that became slower in the second branch:\n\n")
            f.write("| Function | Branch 1 | Branch 2 | Difference | % Change |\n")
            f.write("|----------|----------|----------|------------|----------|\n")
            
            for func_info in results['degraded'][:20]:
                func_name = func_info['function'][:80]  # Truncate long names
                f.write(f"| `{func_name}` | ")
                f.write(f"{func_info['cumtime1']:.4f}s | ")
                f.write(f"{func_info['cumtime2']:.4f}s | ")
                f.write(f"+{func_info['cumtime_diff']:.4f}s | ")
                f.write(f"+{func_info['cumtime_diff_pct']:.2f}% |\n")
            
            f.write("\n")
        
        # Top improved functions
        if results['improved']:
            f.write("## Top 20 Improved Functions (Faster)\n\n")
            f.write("Functions that became faster in the second branch:\n\n")
            f.write("| Function | Branch 1 | Branch 2 | Difference | % Change |\n")
            f.write("|----------|----------|----------|------------|----------|\n")
            
            for func_info in results['improved'][:20]:
                func_name = func_info['function'][:80]
                f.write(f"| `{func_name}` | ")
                f.write(f"{func_info['cumtime1']:.4f}s | ")
                f.write(f"{func_info['cumtime2']:.4f}s | ")
                f.write(f"{func_info['cumtime_diff']:.4f}s | ")
                f.write(f"{func_info['cumtime_diff_pct']:.2f}% |\n")
            
            f.write("\n")
        
        # Backtrader-specific analysis
        f.write("## Backtrader-Specific Functions Analysis\n\n")
        
        backtrader_degraded = [f for f in results['degraded'] 
                              if 'backtrader' in f['function'].lower()]
        backtrader_improved = [f for f in results['improved'] 
                              if 'backtrader' in f['function'].lower()]
        
        f.write(f"- Backtrader functions degraded: **{len(backtrader_degraded)}**\n")
        f.write(f"- Backtrader functions improved: **{len(backtrader_improved)}**\n\n")
        
        if backtrader_degraded:
            f.write("### Top 10 Degraded Backtrader Functions\n\n")
            f.write("| Function | Cumtime Diff | % Change |\n")
            f.write("|----------|--------------|----------|\n")
            
            for func_info in backtrader_degraded[:10]:
                func_name = func_info['function'][:80]
                f.write(f"| `{func_name}` | ")
                f.write(f"+{func_info['cumtime_diff']:.4f}s | ")
                f.write(f"+{func_info['cumtime_diff_pct']:.2f}% |\n")
            
            f.write("\n")
        
        # Recommendations
        f.write("## Recommendations\n\n")
        
        if overall['time_diff'] > 0:
            f.write("### ⚠️ Performance Regression Detected\n\n")
            f.write(f"The second branch ({overall['branch2']}) is ")
            f.write(f"**{overall['time_diff_pct']:.2f}% slower** ")
            f.write(f"than the first branch ({overall['branch1']}).\n\n")
            
            f.write("**Actions to take:**\n\n")
            f.write("1. Review the top degraded functions listed above\n")
            f.write("2. Analyze why these functions became slower\n")
            f.write("3. Consider reverting changes or implementing optimizations\n")
            f.write("4. Profile individual functions for deeper analysis\n\n")
        else:
            f.write("### ✅ Performance Improvement Detected\n\n")
            f.write(f"The second branch ({overall['branch2']}) is ")
            f.write(f"**{abs(overall['time_diff_pct']):.2f}% faster** ")
            f.write(f"than the first branch ({overall['branch1']}).\n\n")
            
            f.write("**Good job! Consider:**\n\n")
            f.write("1. Documenting the optimizations made\n")
            f.write("2. Verifying correctness with additional tests\n")
            f.write("3. Applying similar optimizations to other areas\n\n")
        
        # Key areas to investigate
        if backtrader_degraded:
            f.write("### Key Areas to Investigate\n\n")
            
            # Group by module
            modules = defaultdict(list)
            for func_info in backtrader_degraded[:20]:
                # Extract module name
                match = re.search(r'backtrader[/\\](\w+)\.py', func_info['function'])
                if match:
                    module = match.group(1)
                    modules[module].append(func_info)
            
            for module, funcs in sorted(modules.items(), 
                                       key=lambda x: sum(f['cumtime_diff'] for f in x[1]), 
                                       reverse=True):
                total_diff = sum(f['cumtime_diff'] for f in funcs)
                f.write(f"**{module}.py** (+{total_diff:.4f}s)\n")
                for func in funcs[:5]:
                    f.write(f"  - {func['function'].split('(')[1].split(')')[0] if '(' in func['function'] else 'unknown'}")
                    f.write(f": +{func['cumtime_diff']:.4f}s\n")
                f.write("\n")
        
        f.write("\n---\n\n")
        f.write("*Report generated by compare_performance.py*\n")


def main():
    """Main execution function"""
    if len(sys.argv) < 3:
        print("Usage: python compare_performance.py <log_file_1> <log_file_2> [output_file]")
        print()
        print("Example:")
        print("  python compare_performance.py \\")
        print("    performance_profile_master_20251026_120000.log \\")
        print("    performance_profile_remove-metaprogramming_20251026_130000.log")
        print()
        return 1
    
    log_file_1 = sys.argv[1]
    log_file_2 = sys.argv[2]
    output_file = sys.argv[3] if len(sys.argv) > 3 else 'performance_comparison.md'
    
    # Validate input files
    if not os.path.exists(log_file_1):
        print(f"Error: File not found: {log_file_1}")
        return 1
    
    if not os.path.exists(log_file_2):
        print(f"Error: File not found: {log_file_2}")
        return 1
    
    print("=" * 80)
    print("Performance Comparison Tool")
    print("=" * 80)
    print()
    
    # Parse log files
    print(f"Parsing: {log_file_1}")
    header1 = parse_log_header(log_file_1)
    stats1 = parse_function_stats(log_file_1)
    print(f"  Branch: {header1.get('branch', 'unknown')}")
    print(f"  Execution Time: {header1.get('execution_time', 0):.4f}s")
    print(f"  Functions parsed: {len(stats1)}")
    print()
    
    print(f"Parsing: {log_file_2}")
    header2 = parse_log_header(log_file_2)
    stats2 = parse_function_stats(log_file_2)
    print(f"  Branch: {header2.get('branch', 'unknown')}")
    print(f"  Execution Time: {header2.get('execution_time', 0):.4f}s")
    print(f"  Functions parsed: {len(stats2)}")
    print()
    
    # Compare
    print("Comparing performance...")
    results = compare_stats(stats1, stats2, header1, header2)
    print()
    
    # Quick summary
    print("=" * 80)
    print("QUICK SUMMARY")
    print("=" * 80)
    overall = results['overall']
    print(f"Branch 1: {overall['branch1']} - {overall['time1']:.4f}s")
    print(f"Branch 2: {overall['branch2']} - {overall['time2']:.4f}s")
    print(f"Difference: {overall['time_diff']:+.4f}s ({overall['time_diff_pct']:+.2f}%)")
    
    if overall['time_diff'] > 0:
        print("⚠️  Branch 2 is SLOWER")
    else:
        print("✅ Branch 2 is FASTER")
    
    print()
    print(f"Functions degraded: {len(results['degraded'])}")
    print(f"Functions improved: {len(results['improved'])}")
    print()
    
    # Generate report
    print(f"Generating detailed report: {output_file}")
    generate_comparison_report(results, output_file)
    print(f"✅ Report saved to: {output_file}")
    print()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())


