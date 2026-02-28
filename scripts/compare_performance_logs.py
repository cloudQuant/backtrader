#!/usr/bin/env python
"""Compare two performance profiling logs and generate a detailed report.

This script parses two performance log files (baseline and current), extracts
function call statistics, and generates a comparison report showing performance
improvements and regressions.

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

    Args:
        filepath: Path to the performance log file.

    Returns:
        dict: A dictionary containing:
            - 'total_time': Total execution time in seconds
            - 'functions': Dictionary mapping function names to statistics
              (ncalls, tottime, cumtime)
            - 'strategies_count': Number of strategies tested
            - 'successful': Number of successful tests
            - 'failed': Number of failed tests
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
    """Normalize function name for comparison across logs.

    Args:
        func_name: The function name to normalize.

    Returns:
        A normalized function name for comparison.
    """
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
    """Compare two parsed log results.

    Args:
        baseline: Parsed baseline log data.
        current: Parsed current log data.

    Returns:
        dict: Comparison results including:
            - time_change: Difference in total execution time
            - time_pct_change: Percentage change in execution time
            - aggregate_change: Difference in aggregate time
            - functions_reduced: List of functions with reduced calls
            - functions_increased: List of functions with increased calls
            - functions_removed: Functions in baseline but not in current
            - functions_added: Functions in current but not in baseline
            - top_improvements: Top 20 functions with most call reductions
            - top_regressions: Top 20 functions with most call increases
    """
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
    """Format number with commas.

    Args:
        n: The number to format.

    Returns:
        Formatted number string with comma separators.
    """
    return f"{n:,}"


def format_pct(pct: float) -> str:
    """Format percentage with sign.

    Args:
        pct: The percentage value to format.

    Returns:
        Formatted percentage string with + or - sign.
    """
    if pct >= 0:
        return f"+{pct:.1f}%"
    return f"{pct:.1f}%"


def generate_report(baseline_path: str, current_path: str, baseline: dict,
                   current: dict, comparison: dict) -> str:
    """Generate a detailed comparison report.

    Args:
        baseline_path: Path to baseline log file.
        current_path: Path to current log file.
        baseline: Parsed baseline data.
        current: Parsed current data.
        comparison: Comparison results.

    Returns:
        A formatted report string.
    """
    lines = []

    lines.append("=" * 80)
    lines.append("Performance Log Comparison Report")
    lines.append("=" * 80)
    lines.append("")

    lines.append("## File Information")
    lines.append(f"- **Baseline**: {baseline_path}")
    lines.append(f"- **Current**: {current_path}")
    lines.append("")

    # Overall summary
    lines.append("## Overall Performance Comparison")
    lines.append("")
    lines.append("| Metric | Baseline | Current | Change |")
    lines.append("|--------|----------|---------|--------|")

    baseline_time = baseline.get('total_time', 0)
    current_time = current.get('total_time', 0)
    time_diff = current_time - baseline_time
    time_pct = (time_diff / baseline_time * 100) if baseline_time > 0 else 0

    time_indicator = "Improved" if time_diff < 0 else ("Increased" if time_diff > 0 else "Unchanged")
    lines.append(f"| Total Execution Time | {baseline_time:.2f}s | {current_time:.2f}s | {time_diff:+.2f}s ({format_pct(time_pct)}) {time_indicator} |")

    if baseline.get('aggregate_time') and current.get('aggregate_time'):
        agg_base = baseline['aggregate_time']
        agg_curr = current['aggregate_time']
        agg_diff = agg_curr - agg_base
        agg_pct = (agg_diff / agg_base * 100) if agg_base > 0 else 0
        agg_indicator = "Improved" if agg_diff < 0 else "Increased"
        lines.append(f"| Aggregate Execution Time | {agg_base:.2f}s | {agg_curr:.2f}s | {agg_diff:+.2f}s ({format_pct(agg_pct)}) {agg_indicator} |")

    lines.append(f"| Strategy Count | {baseline.get('strategies_count', 0)} | {current.get('strategies_count', 0)} | - |")
    lines.append(f"| Successful | {baseline.get('successful', 0)} | {current.get('successful', 0)} | - |")
    lines.append("")

    # Functions with reduced calls
    lines.append("## Functions with Reduced Calls (Optimizations)")
    lines.append("")

    if comparison['functions_reduced']:
        lines.append("| Function | Baseline Calls | Current Calls | Reduction | Reduction % | Time Change |")
        lines.append("|----------|----------------|---------------|-----------|-------------|--------------|")

        for entry in comparison['top_improvements'][:30]:
            name = entry['short_name'][:50]
            old_calls = format_number(entry['old_calls'])
            new_calls = format_number(entry['new_calls'])
            diff = format_number(abs(entry['call_diff']))
            pct = f"{entry['change_pct']:.1f}%"
            time_diff = f"{entry['time_diff']:+.2f}s"
            lines.append(f"| `{name}` | {old_calls} | {new_calls} | -{diff} | {pct} | {time_diff} |")
    else:
        lines.append("*No functions with reduced calls*")
    lines.append("")

    # Functions with increased calls
    lines.append("## Functions with Increased Calls (Attention Required)")
    lines.append("")

    if comparison['functions_increased']:
        lines.append("| Function | Baseline Calls | Current Calls | Increase | Increase % | Time Change |")
        lines.append("|----------|----------------|---------------|----------|------------|--------------|")

        for entry in comparison['top_regressions'][:20]:
            name = entry['short_name'][:50]
            old_calls = format_number(entry['old_calls'])
            new_calls = format_number(entry['new_calls'])
            diff = format_number(entry['call_diff'])
            pct = f"+{entry['change_pct']:.1f}%"
            time_diff = f"{entry['time_diff']:+.2f}s"
            lines.append(f"| `{name}` | {old_calls} | {new_calls} | +{diff} | {pct} | {time_diff} |")
    else:
        lines.append("*No functions with increased calls*")
    lines.append("")

    # Key builtin functions comparison
    lines.append("## Built-in Function Call Comparison")
    lines.append("")

    builtin_funcs = ['builtins.len', 'builtins.isinstance', 'builtins.hasattr',
                     'builtins.getattr', 'builtins.setattr']

    lines.append("| Built-in Function | Baseline Calls | Current Calls | Change |")
    lines.append("|-------------------|----------------|---------------|--------|")

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
            indicator = "Improved" if diff < 0 else ("Increased" if diff > 0 else "Unchanged")
            lines.append(f"| `{builtin}` | {format_number(old_calls)} | {format_number(new_calls)} | {format_number(diff)} ({format_pct(pct)}) {indicator} |")

    lines.append("")

    # Summary statistics
    lines.append("## Summary Statistics")
    lines.append("")
    lines.append(f"- **Functions with reduced calls**: {len(comparison['functions_reduced'])}")
    lines.append(f"- **Functions with increased calls**: {len(comparison['functions_increased'])}")
    lines.append(f"- **New functions**: {len(comparison['functions_added'])}")
    lines.append(f"- **Removed functions**: {len(comparison['functions_removed'])}")
    lines.append("")

    # Total call reduction
    total_reduced = sum(abs(e['call_diff']) for e in comparison['functions_reduced'])
    total_increased = sum(e['call_diff'] for e in comparison['functions_increased'])
    net_change = total_increased - total_reduced

    lines.append(f"- **Total calls reduced**: {format_number(total_reduced)}")
    lines.append(f"- **Total calls increased**: {format_number(total_increased)}")
    lines.append(f"- **Net change**: {format_number(net_change)}")
    lines.append("")

    lines.append("=" * 80)
    lines.append("Report generation complete")
    lines.append("=" * 80)

    return "\n".join(lines)


def main() -> int:
    """Main entry point for the comparison script.

    Returns:
        Exit code (0 for success, 1 for error).
    """
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
