#!/usr/bin/env python3
"""Performance Log Comparison Analysis Tool.

This module provides tools for comparing two Python profiler logs to identify
performance regressions and improvements between different code versions,
typically used to compare the master branch against the remove-metaprogramming
branch.

The tool performs comprehensive analysis including:
    - Basic metric comparison (execution time, call counts)
    - Identification of new performance bottlenecks
    - Detection of severely degraded functions
    - Analysis of call count explosions
    - Per-call time increase detection
    - Top function ranking comparison
    - Summary of key findings

Usage:
    python analyze_performance_diff.py <master_log> <remove_log>

Example:
    python analyze_performance_diff.py \\
        performance_profile_master_20251026_181304.log \\
        performance_profile_remove-metaprogramming_20251026_215555.log
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class FunctionStats:
    """Statistics for a single function from profiler output.

    This dataclass stores performance metrics for individual functions
    extracted from cProfile output.

    Attributes:
        ncalls (int): Number of calls to this function.
        tottime (float): Total time spent in this function (excluding subcalls).
        percall_tot (float): Average time per call (excluding subcalls).
        cumtime (float): Cumulative time (including time in subcalls).
        percall_cum (float): Average cumulative time per call.
        filename (str): Source file containing the function.
        lineno (str): Line number of function definition.
        funcname (str): Name of the function.

    Properties:
        full_name (str): Full identifier in format "filename:lineno(funcname)".
    """

    ncalls: int
    tottime: float
    percall_tot: float
    cumtime: float
    percall_cum: float
    filename: str
    lineno: str
    funcname: str

    @property
    def full_name(self):
        """Get full function identifier.

        Returns:
            str: Function identifier in format "filename:lineno(funcname)".
        """
        return f"{self.filename}:{self.lineno}({self.funcname})"


@dataclass
class ProfileReport:
    """Complete performance analysis report from a profiler log.

    This dataclass aggregates all performance metrics extracted from a
    single cProfile log file.

    Attributes:
        branch (str): Git branch name for this profile run.
        commit (str): Git commit hash for this profile run.
        total_time (float): Total execution time in seconds.
        total_calls (int): Total number of function calls.
        primitive_calls (int): Number of primitive (non-recursive) calls.
        total_functions (int): Total number of unique functions called.
        functions (Dict[str, FunctionStats]): Dictionary mapping function full_name
            to FunctionStats objects.
    """

    branch: str
    commit: str
    total_time: float
    total_calls: int
    primitive_calls: int
    total_functions: int
    functions: Dict[str, FunctionStats]


def parse_log_file(log_path: str) -> ProfileReport:
    """Parse performance log file and extract structured data.

    This function reads a Python profiler log file and extracts:
    - Git metadata (branch, commit)
    - Execution metrics (time, calls)
    - Per-function statistics from SECTION 2

    Args:
        log_path (str): Path to the profiler log file.

    Returns:
        ProfileReport: Structured performance data.

    Raises:
        FileNotFoundError: If the log file cannot be found.
        ValueError: If the log file format is invalid.

    Note:
        The function specifically looks for "SECTION 2: TOP 50 FUNCTIONS BY TOTAL TIME"
        to extract function statistics. This section must exist in the log.
    """
    with open(log_path, encoding="utf-8") as f:
        content = f.read()

    # Extract basic information (git metadata and execution time)
    branch_match = re.search(r"Git Branch: (.+)", content)
    commit_match = re.search(r"Git Commit: (.+)", content)
    time_match = re.search(r"Total Execution Time: ([\d.]+) seconds", content)

    branch = branch_match.group(1) if branch_match else "Unknown"
    commit = commit_match.group(1) if commit_match else "Unknown"
    total_time = float(time_match.group(1)) if time_match else 0.0

    # Extract call statistics
    # Format: "1234567 function calls (1234567 primitive calls) in 12.34 seconds"
    calls_match = re.search(
        r"(\d+) function calls \((\d+) primitive calls\) in ([\d.]+) seconds", content
    )
    if calls_match:
        total_calls = int(calls_match.group(1))
        primitive_calls = int(calls_match.group(2))
    else:
        total_calls = primitive_calls = 0

    # Extract function count
    reduced_match = re.search(r"List reduced from (\d+)", content)
    total_functions = int(reduced_match.group(1)) if reduced_match else 0

    # Parse function statistics from SECTION 2
    functions = {}

    # Find SECTION 2: TOP 50 FUNCTIONS BY TOTAL TIME
    section2_start = content.find("SECTION 2: TOP 50 FUNCTIONS BY TOTAL TIME")
    if section2_start != -1:
        section2_content = content[section2_start : section2_start + 20000]

        # Match function lines
        # Format: ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        pattern = (
            r"(\d+(?:/\d+)?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+?):(\d+)\((.+?)\)"
        )

        for match in re.finditer(pattern, section2_content):
            ncalls_str = match.group(1)
            # Handle ncalls possibly containing recursive calls (e.g., "1865/1660")
            if "/" in ncalls_str:
                ncalls = int(ncalls_str.split("/")[0])
            else:
                ncalls = int(ncalls_str)

            func_stat = FunctionStats(
                ncalls=ncalls,
                tottime=float(match.group(2)),
                percall_tot=float(match.group(3)),
                cumtime=float(match.group(4)),
                percall_cum=float(match.group(5)),
                filename=match.group(6),
                lineno=match.group(7),
                funcname=match.group(8),
            )

            functions[func_stat.full_name] = func_stat

    return ProfileReport(
        branch=branch,
        commit=commit,
        total_time=total_time,
        total_calls=total_calls,
        primitive_calls=primitive_calls,
        total_functions=total_functions,
        functions=functions,
    )


def compare_reports(master: ProfileReport, remove: ProfileReport) -> None:
    """Compare two performance reports and print detailed analysis.

    This function performs a comprehensive comparison between two performance
    reports, typically comparing the master branch against the remove-metaprogramming
    branch. It prints seven sections of analysis:

    1. Basic Information Comparison - Overall metrics
    2. New Performance Bottlenecks - Functions only in remove version with time > 0.05s
    3. Most Severely Degraded Functions - Functions with total time increase > 0.01s
    4. Functions with Exploded Call Counts - Functions with call count increase > 10x
    5. Functions with Increased Per-Call Time - Functions with per-call time increase > 10x
    6. Top 10 Most Time-Consuming Functions - Side-by-side comparison
    7. Key Findings Summary - Aggregate statistics

    Args:
        master (ProfileReport): Baseline performance report (master branch).
        remove (ProfileReport): Comparison performance report (remove-metaprogramming branch).

    Side Effects:
        Prints detailed comparison report to stdout.

    Example:
        >>> master_report = parse_log_file("master_profile.log")
        >>> remove_report = parse_log_file("remove_profile.log")
        >>> compare_reports(master_report, remove_report)
        This will print a comprehensive performance comparison.
    """

    print("=" * 100)
    print("BACKTRADER PERFORMANCE COMPARISON ANALYSIS")
    print("=" * 100)
    print()

    # 1. Basic information comparison
    print("[1] Basic Information Comparison")
    print("-" * 100)
    print(f"{'Metric':<30} {'Master':<20} {'Remove':<20} {'Change':<30}")
    print("-" * 100)

    time_diff = remove.total_time - master.total_time
    time_pct = (time_diff / master.total_time) * 100
    print(
        f"{'Total execution time':<30} {master.total_time:<20.4f} {remove.total_time:<20.4f} {f'+{time_pct:.1f}%  (+{time_diff:.2f}s)':<30}"
    )

    calls_diff = remove.total_calls - master.total_calls
    calls_pct = (calls_diff / master.total_calls) * 100
    print(
        f"{'Total function calls':<30} {master.total_calls:<20,} {remove.total_calls:<20,} {f'+{calls_pct:.1f}%  (+{calls_diff:,})':<30}"
    )

    funcs_diff = remove.total_functions - master.total_functions
    funcs_pct = (funcs_diff / master.total_functions) * 100
    print(
        f"{'Function types count':<30} {master.total_functions:<20,} {remove.total_functions:<20,} {f'+{funcs_pct:.1f}%  (+{funcs_diff})':<30}"
    )

    print()
    print()

    # 2. New performance bottlenecks (high-cost functions only in remove version)
    print("[2] New Performance Bottlenecks (only in Remove version with time >0.05s)")
    print("-" * 100)

    new_bottlenecks = []
    for func_name, func_stat in remove.functions.items():
        if func_name not in master.functions and func_stat.tottime > 0.05:
            new_bottlenecks.append((func_name, func_stat))

    new_bottlenecks.sort(key=lambda x: x[1].tottime, reverse=True)

    if new_bottlenecks:
        print(f"{'Function Name':<80} {'Calls':<15} {'Total Time(s)':<15}")
        print("-" * 100)
        for func_name, func_stat in new_bottlenecks[:20]:
            print(f"{func_name:<80} {func_stat.ncalls:<15,} {func_stat.tottime:<15.4f}")
    else:
        print("No new significant performance bottlenecks found")

    print()
    print()

    # 3. Most severely degraded functions (in both versions, but remove version significantly slower)
    print("[3] Most Severely Degraded Functions (total time increase >0.01s)")
    print("-" * 100)

    degraded_funcs = []
    for func_name, master_stat in master.functions.items():
        if func_name in remove.functions:
            remove_stat = remove.functions[func_name]
            time_diff = remove_stat.tottime - master_stat.tottime
            if time_diff > 0.01:
                # Calculate percentage increase, cap at 999% to avoid display issues
                pct = (
                    (time_diff / master_stat.tottime * 100)
                    if master_stat.tottime > 0
                    else 999
                )
                degraded_funcs.append(
                    (
                        func_name,
                        master_stat,
                        remove_stat,
                        time_diff,
                        pct,
                    )
                )

    degraded_funcs.sort(key=lambda x: x[3], reverse=True)

    if degraded_funcs:
        print(
            f"{'Function Name':<70} {'Master(s)':<12} {'Remove(s)':<12} {'Increase(s)':<12} {'Growth(%)':<12}"
        )
        print("-" * 100)
        for func_name, master_stat, remove_stat, diff, pct in degraded_funcs[:20]:
            # Truncate function name to fit display
            short_name = func_name if len(func_name) <= 70 else func_name[:67] + "..."
            print(
                f"{short_name:<70} {master_stat.tottime:<12.4f} {remove_stat.tottime:<12.4f} {diff:<12.4f} {pct:<12.1f}"
            )
    else:
        print("No significant performance degradation found")

    print()
    print()

    # 4. Functions with exploded call counts
    print("[4] Functions with Exploded Call Counts (increase >10x)")
    print("-" * 100)

    call_explosion = []
    for func_name, master_stat in master.functions.items():
        if func_name in remove.functions:
            remove_stat = remove.functions[func_name]
            if master_stat.ncalls > 0:
                call_ratio = remove_stat.ncalls / master_stat.ncalls
                if call_ratio > 10:
                    call_explosion.append((func_name, master_stat, remove_stat, call_ratio))

    call_explosion.sort(key=lambda x: x[3], reverse=True)

    if call_explosion:
        print(f"{'Function Name':<70} {'Master Calls':<15} {'Remove Calls':<15} {'Ratio':<12}")
        print("-" * 100)
        for func_name, master_stat, remove_stat, ratio in call_explosion[:20]:
            short_name = func_name if len(func_name) <= 70 else func_name[:67] + "..."
            print(
                f"{short_name:<70} {master_stat.ncalls:<15,} {remove_stat.ncalls:<15,} {ratio:<12.1f}x"
            )
    else:
        print("No functions with exploded call counts found")

    print()
    print()

    # 5. Functions with most increased per-call time
    print("[5] Functions with Most Increased Per-Call Time (percall increase >10x)")
    print("-" * 100)

    percall_increase = []
    for func_name, master_stat in master.functions.items():
        if func_name in remove.functions:
            remove_stat = remove.functions[func_name]
            # Avoid division by near-zero values
            if master_stat.percall_tot > 0.000001:
                ratio = remove_stat.percall_tot / master_stat.percall_tot
                if ratio > 10:
                    percall_increase.append((func_name, master_stat, remove_stat, ratio))

    percall_increase.sort(key=lambda x: x[3], reverse=True)

    if percall_increase:
        print(f"{'Function Name':<70} {'Master/Call(ms)':<15} {'Remove/Call(ms)':<15} {'Ratio':<12}")
        print("-" * 100)
        for func_name, master_stat, remove_stat, ratio in percall_increase[:20]:
            short_name = func_name if len(func_name) <= 70 else func_name[:67] + "..."
            master_ms = master_stat.percall_tot * 1000  # Convert to milliseconds
            remove_ms = remove_stat.percall_tot * 1000
            print(f"{short_name:<70} {master_ms:<15.6f} {remove_ms:<15.6f} {ratio:<12.1f}x")
    else:
        print("No functions with significantly increased per-call time found")

    print()
    print()

    # 6. Top 10 most time-consuming functions comparison
    print("[6] Top 10 Most Time-Consuming Functions Comparison")
    print("-" * 100)

    master_top10 = sorted(master.functions.items(), key=lambda x: x[1].tottime, reverse=True)[:10]
    remove_top10 = sorted(remove.functions.items(), key=lambda x: x[1].tottime, reverse=True)[:10]

    print("\nMaster Version Top 10:")
    print(f"{'Rank':<5} {'Function Name':<70} {'Time(s)':<12} {'Calls':<15}")
    print("-" * 100)
    for i, (func_name, func_stat) in enumerate(master_top10, 1):
        short_name = func_name if len(func_name) <= 70 else func_name[:67] + "..."
        print(f"{i:<5} {short_name:<70} {func_stat.tottime:<12.4f} {func_stat.ncalls:<15,}")

    print()
    print("Remove Version Top 10:")
    print(f"{'Rank':<5} {'Function Name':<70} {'Time(s)':<12} {'Calls':<15}")
    print("-" * 100)
    for i, (func_name, func_stat) in enumerate(remove_top10, 1):
        short_name = func_name if len(func_name) <= 70 else func_name[:67] + "..."
        print(f"{i:<5} {short_name:<70} {func_stat.tottime:<12.4f} {func_stat.ncalls:<15,}")

    print()
    print()

    # 7. Key metrics summary
    print("[7] Key Findings Summary")
    print("-" * 100)

    # Calculate time for backtrader-related functions
    master_bt_time = sum(
        stat.tottime for name, stat in master.functions.items() if "backtrader" in name
    )
    remove_bt_time = sum(
        stat.tottime for name, stat in remove.functions.items() if "backtrader" in name
    )

    print(f"1. Total execution time increase: {time_pct:.1f}% ({time_diff:.2f}s)")
    print(f"2. Function call count increase: {calls_pct:.1f}%")
    print(f"3. New performance bottleneck functions: {len(new_bottlenecks)}")
    print(f"4. Significantly degraded functions: {len(degraded_funcs)}")
    print(f"5. Call explosion functions (>10x): {len(call_explosion)}")
    print(f"6. Per-call explosion functions (>10x): {len(percall_increase)}")
    print(
        f"7. Backtrader-related functions total time: Master={master_bt_time:.2f}s, Remove={remove_bt_time:.2f}s (increase {remove_bt_time-master_bt_time:.2f}s)"
    )

    print()
    print("=" * 100)


def main():
    """Main execution function for performance comparison tool.

    Parses command line arguments, loads both performance logs, and
    generates a comprehensive comparison report.

    Usage:
        python analyze_performance_diff.py <master_log_path> <remove_log_path>

    Args:
        sys.argv[1]: Path to master branch profiler log.
        sys.argv[2]: Path to remove-metaprogramming branch profiler log.

    Returns:
        None

    Raises:
        SystemExit: Exits with code 1 if incorrect arguments provided.

    Example:
        >>> python analyze_performance_diff.py \\
        ...     performance_profile_master_20251026_181304.log \\
        ...     performance_profile_remove-metaprogramming_20251026_215555.log
    """
    import sys

    if len(sys.argv) != 3:
        print("Usage: python analyze_performance_diff.py <master_log_path> <remove_log_path>")
        print()
        print("Example:")
        print("  python analyze_performance_diff.py \\")
        print("    performance_profile_master_20251026_181304.log \\")
        print("    performance_profile_remove-metaprogramming_20251026_215555.log")
        sys.exit(1)

    master_log = sys.argv[1]
    remove_log = sys.argv[2]

    print(f"Parsing Master version log: {master_log}")
    master_report = parse_log_file(master_log)
    print(f"  - Branch: {master_report.branch}")
    print(f"  - Commit: {master_report.commit}")
    print(f"  - Total time: {master_report.total_time}s")
    print(f"  - Parsed {len(master_report.functions)} functions")
    print()

    print(f"Parsing Remove version log: {remove_log}")
    remove_report = parse_log_file(remove_log)
    print(f"  - Branch: {remove_report.branch}")
    print(f"  - Commit: {remove_report.commit}")
    print(f"  - Total time: {remove_report.total_time}s")
    print(f"  - Parsed {len(remove_report.functions)} functions")
    print()
    print()

    # Perform comparison analysis
    compare_reports(master_report, remove_report)


if __name__ == "__main__":
    main()
