#!/usr/bin/env python
"""
Analyze current performance logs and compare before/after optimization status.
"""

import re
import sys
from collections import defaultdict


def parse_log_file(filename):
    """Parse performance log file."""
    with open(filename, encoding="utf-8") as f:
        content = f.read()

    # Extract overall information
    total_calls_match = re.search(r"(\d+)\s+function calls.*in\s+([\d.]+)\s+seconds", content)
    if total_calls_match:
        total_calls = int(total_calls_match.group(1))
        total_time = float(total_calls_match.group(2))
    else:
        total_calls, total_time = 0, 0.0

    # Extract function statistics
    functions = []

    # Find statistics table section
    pattern = (
        r"\s+(\d+(?:/\d+)?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([^:]+):(\d+)\(([^)]+)\)"
    )

    for match in re.finditer(pattern, content):
        ncalls = match.group(1)
        tottime = float(match.group(2))
        percall_tot = float(match.group(3))
        cumtime = float(match.group(4))
        percall_cum = float(match.group(5))
        filename = match.group(6)
        lineno = match.group(7)
        funcname = match.group(8)

        # Parse ncalls (may contain recursive calls)
        if "/" in ncalls:
            calls, primitive = ncalls.split("/")
            ncalls_num = int(calls)
        else:
            ncalls_num = int(ncalls)

        functions.append(
            {
                "ncalls": ncalls_num,
                "tottime": tottime,
                "cumtime": cumtime,
                "filename": filename,
                "lineno": lineno,
                "funcname": funcname,
                "fullname": f"{filename}:{lineno}({funcname})",
            }
        )

    return {"total_calls": total_calls, "total_time": total_time, "functions": functions}


def analyze_bottlenecks(log_data):
    """Analyze performance bottlenecks."""
    functions = log_data["functions"]

    print("\n" + "=" * 100)
    print("Current Performance Bottleneck Analysis")
    print("=" * 100)
    print(f"\nTotal execution time: {log_data['total_time']:.2f}s")
    print(f"Total function calls: {log_data['total_calls']:,}")
    print(f"Average per call: {(log_data['total_time']/log_data['total_calls']*1000000):.2f} microseconds")

    # Sort by cumulative time
    print("\n" + "-" * 100)
    print("TOP 20 Most Time-Consuming Functions (by cumulative time)")
    print("-" * 100)
    print(f"{'Rank':<5} {'Function':<60} {'Calls':<15} {'Cum Time':<12} {'Pct':<8}")
    print("-" * 100)

    sorted_by_cumtime = sorted(functions, key=lambda x: x["cumtime"], reverse=True)[:20]
    for i, func in enumerate(sorted_by_cumtime, 1):
        percent = func["cumtime"] / log_data["total_time"] * 100
        print(
            f"{i:<5} {func['funcname']:<60} {func['ncalls']:>14,} {func['cumtime']:>11.3f}s {percent:>7.1f}%"
        )

    # Critical bottleneck function analysis
    print("\n" + "-" * 100)
    print("Critical Bottleneck Functions Detailed Analysis")
    print("-" * 100)

    bottlenecks = {
        "hasattr": [],
        "getattr": [],
        "setattr": [],
        "isinstance": [],
        "isnan": [],
        "__getattr__": [],
        "__setattr__": [],
        "__getitem__": [],
        "forward": [],
    }

    for func in functions:
        funcname = func["funcname"].lower()
        for key in bottlenecks:
            if key in funcname:
                bottlenecks[key].append(func)

    for key, funcs in bottlenecks.items():
        if funcs:
            total_calls = sum(f["ncalls"] for f in funcs)
            total_time = sum(f["cumtime"] for f in funcs)
            print(f"\n{key.upper()}:")
            print(f"  Total calls: {total_calls:,}")
            print(f"  Total time: {total_time:.3f}s ({total_time/log_data['total_time']*100:.1f}%)")
            if funcs:
                print(f"  Main sources:")
                for f in sorted(funcs, key=lambda x: x["cumtime"], reverse=True)[:3]:
                    print(f"    - {f['fullname']}: {f['ncalls']:,} calls, {f['cumtime']:.3f}s")

    return bottlenecks


def compare_with_baseline(current_log, baseline_file):
    """Compare with baseline."""
    try:
        baseline_data = parse_log_file(baseline_file)

        print("\n" + "=" * 100)
        print(f"Comparison with baseline: {baseline_file}")
        print("=" * 100)

        print(f"\n{'Metric':<30} {'Baseline':<20} {'Current':<20} {'Change':<20}")
        print("-" * 100)

        # Total execution time comparison
        time_diff = current_log["total_time"] - baseline_data["total_time"]
        time_pct = (
            (time_diff / baseline_data["total_time"] * 100)
            if baseline_data["total_time"] > 0
            else 0
        )
        print(
            f"{'Total execution time':<30} {baseline_data['total_time']:>19.2f}s {current_log['total_time']:>19.2f}s {time_diff:+19.2f}s ({time_pct:+.1f}%)"
        )

        # Total calls comparison
        calls_diff = current_log["total_calls"] - baseline_data["total_calls"]
        calls_pct = (
            (calls_diff / baseline_data["total_calls"] * 100)
            if baseline_data["total_calls"] > 0
            else 0
        )
        print(
            f"{'Total function calls':<30} {baseline_data['total_calls']:>19,} {current_log['total_calls']:>19,} {calls_diff:+19,} ({calls_pct:+.1f}%)"
        )

        # Key function comparison
        print("\nKey Function Call Count Comparison:")
        print(f"{'Function':<30} {'Baseline Calls':<20} {'Current Calls':<20} {'Change':<20}")
        print("-" * 100)

        key_functions = [
            "hasattr",
            "getattr",
            "setattr",
            "isinstance",
            "__getattr__",
            "__setattr__",
            "__getitem__",
        ]

        for key in key_functions:
            baseline_funcs = [f for f in baseline_data["functions"] if key in f["funcname"].lower()]
            current_funcs = [f for f in current_log["functions"] if key in f["funcname"].lower()]

            baseline_calls = sum(f["ncalls"] for f in baseline_funcs)
            current_calls = sum(f["ncalls"] for f in current_funcs)

            if baseline_calls > 0 or current_calls > 0:
                diff = current_calls - baseline_calls
                pct = (diff / baseline_calls * 100) if baseline_calls > 0 else float("inf")
                if pct == float("inf"):
                    print(f"{key:<30} {baseline_calls:>19,} {current_calls:>19,} {diff:+19,} (NEW)")
                else:
                    print(
                        f"{key:<30} {baseline_calls:>19,} {current_calls:>19,} {diff:+19,} ({pct:+.1f}%)"
                    )

    except FileNotFoundError:
        print(f"\nWarning: Baseline file not found {baseline_file}")
    except Exception as e:
        print(f"\nError: Comparison failed - {e}")


def generate_optimization_recommendations(bottlenecks, log_data):
    """Generate optimization recommendations."""
    print("\n" + "=" * 100)
    print("Optimization Recommendations (by priority)")
    print("=" * 100)

    recommendations = []

    # Analyze hasattr
    if bottlenecks["hasattr"]:
        total_calls = sum(f["ncalls"] for f in bottlenecks["hasattr"])
        total_time = sum(f["cumtime"] for f in bottlenecks["hasattr"])
        if total_calls > 5000000:  # Over 5 million calls
            recommendations.append(
                {
                    "priority": 1,
                    "title": "Optimize hasattr calls",
                    "issue": f"hasattr called {total_calls:,} times, taking {total_time:.2f}s",
                    "solution": "Use try-except (EAFP) instead of hasattr (LBYL)",
                    "expected_gain": f"Reduce {total_calls*0.7:,.0f} calls, save {total_time*0.7:.1f}s",
                    "files": [
                        "backtrader/lineseries.py",
                        "backtrader/linebuffer.py",
                        "backtrader/lineiterator.py",
                    ],
                }
            )

    # Analyze __getattr__
    if bottlenecks["__getattr__"]:
        total_calls = sum(f["ncalls"] for f in bottlenecks["__getattr__"])
        total_time = sum(f["cumtime"] for f in bottlenecks["__getattr__"])
        if total_calls > 500000:
            recommendations.append(
                {
                    "priority": 1,
                    "title": "Implement __getattr__ attribute caching",
                    "issue": f"__getattr__ called {total_calls:,} times, taking {total_time:.2f}s",
                    "solution": "Cache attributes to __dict__ after first access to avoid repeated lookups",
                    "expected_gain": f"Reduce {total_calls*0.8:,.0f} calls, save {total_time*0.6:.1f}s",
                    "files": ["backtrader/lineseries.py"],
                }
            )

    # Analyze __setattr__
    if bottlenecks["__setattr__"]:
        total_calls = sum(f["ncalls"] for f in bottlenecks["__setattr__"])
        total_time = sum(f["cumtime"] for f in bottlenecks["__setattr__"])
        if total_calls > 1000000:
            recommendations.append(
                {
                    "priority": 2,
                    "title": "Optimize __setattr__ performance",
                    "issue": f"__setattr__ called {total_calls:,} times, taking {total_time:.2f}s",
                    "solution": "Use fast path for simple types, reduce internal hasattr calls",
                    "expected_gain": f"Save {total_time*0.5:.1f}s",
                    "files": ["backtrader/lineseries.py"],
                }
            )

    # Analyze isinstance/isnan
    isinstance_calls = sum(f["ncalls"] for f in bottlenecks["isinstance"])
    isnan_calls = sum(f["ncalls"] for f in bottlenecks["isnan"])
    if isinstance_calls > 5000000 or isnan_calls > 2000000:
        isinstance_time = sum(f["cumtime"] for f in bottlenecks["isinstance"])
        isnan_time = sum(f["cumtime"] for f in bottlenecks["isnan"])
        recommendations.append(
            {
                "priority": 2,
                "title": "Optimize isinstance/isnan checks",
                "issue": f"isinstance: {isinstance_calls:,} calls, isnan: {isnan_calls:,} calls",
                "solution": "Use value != value to detect NaN (NaN self-comparison property)",
                "expected_gain": f"Reduce {(isinstance_calls+isnan_calls):,.0f} calls, save {isinstance_time+isnan_time:.1f}s",
                "files": ["backtrader/lineseries.py", "backtrader/linebuffer.py"],
            }
        )

    # Analyze __getitem__
    if bottlenecks["__getitem__"]:
        total_calls = sum(f["ncalls"] for f in bottlenecks["__getitem__"])
        total_time = sum(f["cumtime"] for f in bottlenecks["__getitem__"])
        if total_time > 3.0:
            recommendations.append(
                {
                    "priority": 2,
                    "title": "Optimize __getitem__ method",
                    "issue": f"__getitem__ called {total_calls:,} times, taking {total_time:.2f}s",
                    "solution": "Simplify logic, reduce type checks, use direct array access",
                    "expected_gain": f"Save {total_time*0.5:.1f}s",
                    "files": ["backtrader/lineseries.py", "backtrader/linebuffer.py"],
                }
            )

    # Analyze forward
    if bottlenecks["forward"]:
        total_calls = sum(f["ncalls"] for f in bottlenecks["forward"])
        total_time = sum(f["cumtime"] for f in bottlenecks["forward"])
        if total_time > 5.0:
            recommendations.append(
                {
                    "priority": 3,
                    "title": "Optimize forward method",
                    "issue": f"forward called {total_calls:,} times, taking {total_time:.2f}s",
                    "solution": "Reduce NaN checks, optimize array operations",
                    "expected_gain": f"Save {total_time*0.3:.1f}s",
                    "files": ["backtrader/linebuffer.py", "backtrader/lineseries.py"],
                }
            )

    # Sort by priority
    recommendations.sort(key=lambda x: x["priority"])

    # Print recommendations
    for i, rec in enumerate(recommendations, 1):
        print(
            f"\n{'🔴' if rec['priority'] == 1 else '🟡' if rec['priority'] == 2 else '🟢'} Recommendation #{i}: {rec['title']}"
        )
        print(
            f"   Priority: {'High' if rec['priority'] == 1 else 'Medium' if rec['priority'] == 2 else 'Low'}"
        )
        print(f"   Issue: {rec['issue']}")
        print(f"   Solution: {rec['solution']}")
        print(f"   Expected Gain: {rec['expected_gain']}")
        print(f"   Files: {', '.join(rec['files'])}")

    # Total expected gain
    print("\n" + "=" * 100)
    print("Total Expected Optimization Results")
    print("=" * 100)

    total_expected_time_save = 0
    for rec in recommendations:
        # Extract seconds from expected_gain
        import re

        match = re.search(r"Save ([\d.]+)s", rec["expected_gain"])
        if match:
            total_expected_time_save += float(match.group(1))

    current_time = log_data["total_time"]
    expected_time = current_time - total_expected_time_save
    improvement_pct = (total_expected_time_save / current_time * 100) if current_time > 0 else 0

    print(f"\nCurrent execution time: {current_time:.2f}s")
    print(f"Expected time savings: {total_expected_time_save:.2f}s")
    print(f"Optimized time: {expected_time:.2f}s")
    print(f"Performance improvement: {improvement_pct:.1f}%")

    return recommendations


def main():
    # Analyze current logs
    import glob

    log_files = glob.glob("performance_profile_remove-metaprogramming_*.log")
    if not log_files:
        print("Error: Performance log file not found")
        return 1

    # Use latest log file
    current_log_file = sorted(log_files)[-1]
    print(f"Analyzing log file: {current_log_file}")

    current_data = parse_log_file(current_log_file)
    bottlenecks = analyze_bottlenecks(current_data)

    # Compare with master baseline
    master_log = "performance_profile_master_20251026_230910.log"
    compare_with_baseline(current_data, master_log)

    # Generate optimization recommendations
    recommendations = generate_optimization_recommendations(bottlenecks, current_data)

    # Save report
    report_file = "current_performance_analysis_report.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"# Current Performance Analysis Report\n\n")
        f.write(f"## Basic Information\n\n")
        f.write(f"- Log file: {current_log_file}\n")
        f.write(f"- Total execution time: {current_data['total_time']:.2f}s\n")
        f.write(f"- Total function calls: {current_data['total_calls']:,}\n")
        f.write(
            f"- Analysis time: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        f.write(f"## Optimization Recommendations\n\n")
        for i, rec in enumerate(recommendations, 1):
            f.write(f"### {i}. {rec['title']}\n\n")
            f.write(
                f"**Priority**: {'High 🔴' if rec['priority'] == 1 else 'Medium 🟡' if rec['priority'] == 2 else 'Low 🟢'}\n\n"
            )
            f.write(f"**Issue**: {rec['issue']}\n\n")
            f.write(f"**Solution**: {rec['solution']}\n\n")
            f.write(f"**Expected Gain**: {rec['expected_gain']}\n\n")
            f.write(f"**Files**: {', '.join(rec['files'])}\n\n")

        f.write(f"\n## Detailed Data\n\n")
        f.write(f"See full performance log: {current_log_file}\n")

    print(f"\nReport saved to: {report_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
