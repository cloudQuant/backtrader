#!/usr/bin/env python
"""
Performance Analysis Script for Backtrader Metaclass Removal
Compare performance between master and remove-metaprogramming branches
"""

import re
from collections import defaultdict
from typing import Dict, List, Tuple


def parse_log_header(log_path: str) -> Dict[str, str]:
    """Parse log header to extract metadata."""
    metadata = {}
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            if "Git Branch:" in line:
                metadata["branch"] = line.split(":")[1].strip()
            elif "Git Commit:" in line:
                metadata["commit"] = line.split(":")[1].strip()
            elif "Total Execution Time:" in line:
                metadata["total_time"] = line.split(":")[1].strip()
            elif "function calls" in line and "in" in line and "seconds" in line:
                # Extract total function calls
                match = re.search(r"(\d+)\s+function calls.*in\s+([\d.]+)\s+seconds", line)
                if match:
                    metadata["total_calls"] = match.group(1)
                    metadata["cpu_time"] = match.group(2)
                break
    return metadata


def parse_log_functions(log_path: str) -> List[Dict]:
    """Parse function call data from performance log."""
    functions = []
    in_section = False

    with open(log_path, encoding="utf-8") as f:
        for line in f:
            # Look for the start of SECTION 1
            if "SECTION 1: TOP 50 FUNCTIONS BY CUMULATIVE TIME" in line:
                in_section = True
                continue

            # Skip header lines in section
            if in_section and ("ncalls" in line and "tottime" in line):
                continue

            # End of section
            if in_section and line.strip() == "":
                continue

            if in_section and "SECTION 2:" in line:
                break

            # Parse function line
            if in_section:
                # Pattern: ncalls  tottime  percall  cumtime  percall filename:lineno(function)
                match = re.match(
                    r"\s*(\S+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+)", line
                )
                if match:
                    ncalls = match.group(1)
                    tottime = float(match.group(2))
                    cumtime = float(match.group(4))
                    location = match.group(6)

                    # Extract just ncalls (handle recursive calls like "1683000/612000")
                    if "/" in ncalls:
                        total_calls, primitive_calls = ncalls.split("/")
                    else:
                        total_calls = ncalls
                        primitive_calls = ncalls

                    functions.append(
                        {
                            "ncalls": int(total_calls),
                            "ncalls_primitive": int(primitive_calls),
                            "tottime": tottime,
                            "cumtime": cumtime,
                            "location": location.strip(),
                        }
                    )

    return functions


def extract_function_name(location: str) -> str:
    """Extract normalized function identifier from location."""
    # Pattern: filename:lineno(function)
    # We'll use filename(function) as key, ignoring line numbers
    match = re.match(r"(.+?):(\d+)\((.+?)\)$", location)
    if match:
        filepath = match.group(1)
        # Get just the filename without full path
        filename = filepath.split("\\")[-1].split("/")[-1]
        funcname = match.group(3)
        return f"{filename}({funcname})"
    return location


def compare_logs(master_log: str, remove_meta_log: str) -> None:
    """Compare two performance logs and generate analysis report."""

    print("=" * 100)
    print("BACKTRADER PERFORMANCE REGRESSION ANALYSIS")
    print("Comparing: master vs remove-metaprogramming")
    print("=" * 100)
    print()

    # Parse metadata
    master_meta = parse_log_header(master_log)
    remove_meta = parse_log_header(remove_meta_log)

    print("## 1. OVERALL METRICS COMPARISON")
    print("-" * 100)
    print(f"{'Metric':<40} {'Master':<25} {'Remove-Meta':<25} {'Change'}")
    print("-" * 100)

    # Total execution time
    master_time = float(master_meta["total_time"].split()[0])
    remove_time = float(remove_meta["total_time"].split()[0])
    time_diff = remove_time - master_time
    time_pct = (time_diff / master_time) * 100
    print(
        f"{'Total Execution Time (s)':<40} {master_time:<25.4f} {remove_time:<25.4f} +{time_diff:.4f} (+{time_pct:.2f}%)"
    )

    # Total function calls
    master_calls = int(master_meta["total_calls"])
    remove_calls = int(remove_meta["total_calls"])
    calls_diff = remove_calls - master_calls
    calls_pct = (calls_diff / master_calls) * 100
    print(
        f"{'Total Function Calls':<40} {master_calls:<25,} {remove_calls:<25,} +{calls_diff:,} (+{calls_pct:.2f}%)"
    )

    # CPU time
    master_cpu = float(master_meta["cpu_time"])
    remove_cpu = float(remove_meta["cpu_time"])
    cpu_diff = remove_cpu - master_cpu
    cpu_pct = (cpu_diff / master_cpu) * 100
    print(
        f"{'CPU Time (s)':<40} {master_cpu:<25.4f} {remove_cpu:<25.4f} +{cpu_diff:.4f} (+{cpu_pct:.2f}%)"
    )
    print()

    # Parse function data
    master_funcs = parse_log_functions(master_log)
    remove_funcs = parse_log_functions(remove_meta_log)

    # Build dictionaries keyed by function name
    master_dict = {}
    for func in master_funcs:
        key = extract_function_name(func["location"])
        master_dict[key] = func

    remove_dict = {}
    for func in remove_funcs:
        key = extract_function_name(func["location"])
        remove_dict[key] = func

    # Find functions with significant changes
    print("## 2. FUNCTION CALL COUNT CHANGES (Top Regressions)")
    print("-" * 100)
    print(f"{'Function':<60} {'Master Calls':<20} {'Remove-Meta Calls':<20} {'Change'}")
    print("-" * 100)

    changes = []

    # Compare common functions
    for key in master_dict:
        if key in remove_dict:
            master_ncalls = master_dict[key]["ncalls"]
            remove_ncalls = remove_dict[key]["ncalls"]
            diff = remove_ncalls - master_ncalls
            if diff != 0:
                pct = (diff / master_ncalls * 100) if master_ncalls > 0 else float("inf")
                changes.append(
                    {
                        "function": key,
                        "master_calls": master_ncalls,
                        "remove_calls": remove_ncalls,
                        "diff": diff,
                        "pct": pct,
                    }
                )

    # Also check for new functions in remove-meta
    for key in remove_dict:
        if key not in master_dict:
            changes.append(
                {
                    "function": key,
                    "master_calls": 0,
                    "remove_calls": remove_dict[key]["ncalls"],
                    "diff": remove_dict[key]["ncalls"],
                    "pct": float("inf"),
                }
            )

    # Sort by absolute diff
    changes.sort(key=lambda x: abs(x["diff"]), reverse=True)

    # Show top 30 changes
    for i, change in enumerate(changes[:30]):
        func = change["function"]
        if len(func) > 58:
            func = func[:55] + "..."

        master_c = change["master_calls"]
        remove_c = change["remove_calls"]
        diff = change["diff"]

        if master_c == 0:
            change_str = f"+{diff:,} (NEW)"
        else:
            pct = change["pct"]
            if diff > 0:
                change_str = f"+{diff:,} (+{pct:.1f}%)"
            else:
                change_str = f"{diff:,} ({pct:.1f}%)"

        print(f"{func:<60} {master_c:<20,} {remove_c:<20,} {change_str}")

    print()

    # Time analysis
    print("## 3. FUNCTION TIME CHANGES (Top Time Regressions)")
    print("-" * 100)
    print(f"{'Function':<60} {'Master Time':<20} {'Remove-Meta Time':<20} {'Change'}")
    print("-" * 100)

    time_changes = []
    for key in master_dict:
        if key in remove_dict:
            master_cumtime = master_dict[key]["cumtime"]
            remove_cumtime = remove_dict[key]["cumtime"]
            diff = remove_cumtime - master_cumtime
            if abs(diff) > 0.01:  # Only show significant time changes
                pct = (diff / master_cumtime * 100) if master_cumtime > 0 else float("inf")
                time_changes.append(
                    {
                        "function": key,
                        "master_time": master_cumtime,
                        "remove_time": remove_cumtime,
                        "diff": diff,
                        "pct": pct,
                    }
                )

    # Sort by absolute diff
    time_changes.sort(key=lambda x: abs(x["diff"]), reverse=True)

    # Show top 30
    for change in time_changes[:30]:
        func = change["function"]
        if len(func) > 58:
            func = func[:55] + "..."

        master_t = change["master_time"]
        remove_t = change["remove_time"]
        diff = change["diff"]
        pct = change["pct"]

        if diff > 0:
            change_str = f"+{diff:.3f}s (+{pct:.1f}%)"
        else:
            change_str = f"{diff:.3f}s ({pct:.1f}%)"

        print(f"{func:<60} {master_t:<20.3f} {remove_t:<20.3f} {change_str}")

    print()

    # Summary of key insights
    print("## 4. KEY INSIGHTS & ROOT CAUSE ANALYSIS")
    print("-" * 100)

    # Analyze attribute access patterns
    hasattr_master = master_dict.get("builtins.py(hasattr)", {}).get("ncalls", 0)
    hasattr_remove = remove_dict.get("builtins.py(hasattr)", {}).get("ncalls", 0)

    getattr_master = master_dict.get("builtins.py(getattr)", {}).get(
        "ncalls", 0
    ) or master_dict.get("lineseries.py(__getattr__)", {}).get("ncalls", 0)
    getattr_remove = remove_dict.get("builtins.py(getattr)", {}).get(
        "ncalls", 0
    ) or remove_dict.get("lineseries.py(__getattr__)", {}).get("ncalls", 0)

    setattr_master = master_dict.get("builtins.py(setattr)", {}).get(
        "ncalls", 0
    ) or master_dict.get("lineseries.py(__setattr__)", {}).get("ncalls", 0)
    setattr_remove = remove_dict.get("builtins.py(setattr)", {}).get(
        "ncalls", 0
    ) or remove_dict.get("lineseries.py(__setattr__)", {}).get("ncalls", 0)

    print("\n### Attribute Access Overhead:")
    if hasattr_remove > hasattr_master:
        print(
            f"  - hasattr() calls increased: {hasattr_master:,} → {hasattr_remove:,} (+{hasattr_remove-hasattr_master:,})"
        )
    if getattr_remove > getattr_master:
        print(
            f"  - getattr() calls increased: {getattr_master:,} → {getattr_remove:,} (+{getattr_remove-getattr_master:,})"
        )
    if setattr_remove > setattr_master:
        print(
            f"  - setattr() calls increased: {setattr_master:,} → {setattr_remove:,} (+{setattr_remove-setattr_master:,})"
        )

    print("\n### Missing Optimizations:")
    # Check for _once implementation
    once_remove = remove_dict.get("lineiterator.py(_once)", {})
    if once_remove:
        print(
            f"  - _once() optimization present but may need tuning: {once_remove.get('ncalls', 0):,} calls"
        )

    print("\n### Major Bottlenecks Identified:")
    # Top 5 call count increases
    print("  Top 5 function call increases:")
    for i, change in enumerate(changes[:5], 1):
        if change["master_calls"] > 0:
            print(
                f"    {i}. {change['function']}: +{change['diff']:,} calls (+{change['pct']:.1f}%)"
            )
        else:
            print(f"    {i}. {change['function']}: +{change['diff']:,} calls (NEW)")

    print()


if __name__ == "__main__":
    master_log = "performance_profile_master_20251026_230910.log"
    remove_meta_log = "performance_profile_remove-metaprogramming_20251028_182542.log"

    compare_logs(master_log, remove_meta_log)
