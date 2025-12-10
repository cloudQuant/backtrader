#!/usr/bin/env python
"""
Performance profiling script for backtrader tests
Analyzes function call counts and execution time
"""

import cProfile
import io
import os
import pstats
import subprocess
import sys
import time
from datetime import datetime

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def get_git_branch():
    """Get current git branch name"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except:
        return "unknown"


def get_git_commit():
    """Get current git commit hash"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except:
        return "unknown"


def profile_test(test_module_path):
    """
    Profile the execution of a test module

    Args:
        test_module_path: Path to the test module (e.g., 'tests.original_tests.test_strategy_unoptimized')

    Returns:
        pstats.Stats object containing profiling results
    """
    # Import the test module
    module_parts = test_module_path.replace("/", ".").replace("\\", ".").replace(".py", "")

    # Create profiler
    profiler = cProfile.Profile()

    # Start profiling
    print(f"Starting profiling of {module_parts}...")
    start_time = time.time()

    profiler.enable()

    try:
        # Import and run the test
        if module_parts.startswith("tests."):
            module_name = module_parts
        else:
            module_name = module_parts.replace("tests.", "", 1)

        # Change to the module directory and import
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tests", "original_tests"))

        # Import the test module
        test_module = __import__("test_strategy_optimized", fromlist=["test_run"])

        # Run the test
        test_module.test_run(main=False)

    finally:
        profiler.disable()

    end_time = time.time()
    total_time = end_time - start_time

    print(f"Profiling completed in {total_time:.4f} seconds")

    # Create stats object
    stats = pstats.Stats(profiler)

    return stats, total_time


def generate_report(stats, total_time, output_file="performance_profile.log"):
    """
    Generate detailed performance report and save to file

    Args:
        stats: pstats.Stats object with profiling data
        total_time: Total execution time
        output_file: Output log file path
    """
    # Get git information
    branch = get_git_branch()
    commit = get_git_commit()

    # Open output file
    with open(output_file, "w", encoding="utf-8") as f:
        # Write header
        f.write("=" * 100 + "\n")
        f.write("BACKTRADER PERFORMANCE PROFILING REPORT\n")
        f.write("=" * 100 + "\n\n")

        f.write(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Git Branch: {branch}\n")
        f.write(f"Git Commit: {commit}\n")
        f.write(f"Test File: tests\\original_tests\\test_strategy_optimized.py\n")
        f.write(f"Total Execution Time: {total_time:.4f} seconds\n")
        f.write("\n" + "=" * 100 + "\n\n")

        # Section 1: Top functions by cumulative time
        f.write("SECTION 1: TOP 50 FUNCTIONS BY CUMULATIVE TIME\n")
        f.write("-" * 100 + "\n")
        f.write("(Cumulative time includes time spent in this function and all sub-functions)\n\n")

        stream = io.StringIO()
        stats.stream = stream
        stats.sort_stats("cumulative")
        stats.print_stats(50)
        f.write(stream.getvalue())
        f.write("\n\n")

        # Section 2: Top functions by total time (excluding sub-calls)
        f.write("SECTION 2: TOP 50 FUNCTIONS BY TOTAL TIME (excluding sub-calls)\n")
        f.write("-" * 100 + "\n")
        f.write("(Total time spent in this function only, not including sub-functions)\n\n")

        stream = io.StringIO()
        stats.stream = stream
        stats.sort_stats("tottime")
        stats.print_stats(50)
        f.write(stream.getvalue())
        f.write("\n\n")

        # Section 3: Top functions by call count
        f.write("SECTION 3: TOP 50 FUNCTIONS BY CALL COUNT\n")
        f.write("-" * 100 + "\n")
        f.write("(Functions that are called most frequently)\n\n")

        stream = io.StringIO()
        stats.stream = stream
        stats.sort_stats("ncalls")
        stats.print_stats(50)
        f.write(stream.getvalue())
        f.write("\n\n")

        # Section 4: Backtrader-specific functions
        f.write("SECTION 4: BACKTRADER-SPECIFIC FUNCTIONS (sorted by cumulative time)\n")
        f.write("-" * 100 + "\n")
        f.write("(Filtering for functions in the backtrader module)\n\n")

        stream = io.StringIO()
        stats.stream = stream
        stats.sort_stats("cumulative")
        stats.print_stats("backtrader", 100)
        f.write(stream.getvalue())
        f.write("\n\n")

        # Section 5: Strategy-specific functions
        f.write("SECTION 5: STRATEGY-SPECIFIC FUNCTIONS (sorted by cumulative time)\n")
        f.write("-" * 100 + "\n")
        f.write("(Filtering for strategy.py functions)\n\n")

        stream = io.StringIO()
        stats.stream = stream
        stats.sort_stats("cumulative")
        stats.print_stats("strategy.py", 100)
        f.write(stream.getvalue())
        f.write("\n\n")

        # Section 6: Indicator-specific functions
        f.write("SECTION 6: INDICATOR-SPECIFIC FUNCTIONS (sorted by cumulative time)\n")
        f.write("-" * 100 + "\n")
        f.write("(Filtering for indicator functions)\n\n")

        stream = io.StringIO()
        stats.stream = stream
        stats.sort_stats("cumulative")
        stats.print_stats("indicator", 100)
        f.write(stream.getvalue())
        f.write("\n\n")

        # Section 7: Line buffer operations
        f.write("SECTION 7: LINE BUFFER OPERATIONS (sorted by cumulative time)\n")
        f.write("-" * 100 + "\n")
        f.write("(Filtering for line-related functions)\n\n")

        stream = io.StringIO()
        stats.stream = stream
        stats.sort_stats("cumulative")
        stats.print_stats("line", 100)
        f.write(stream.getvalue())
        f.write("\n\n")

        # Section 8: Detailed call statistics for hot functions
        f.write("SECTION 8: DETAILED CALL STATISTICS\n")
        f.write("-" * 100 + "\n")
        f.write("(Detailed breakdown of function calls and callers)\n\n")

        stream = io.StringIO()
        stats.stream = stream
        stats.sort_stats("cumulative")
        stats.print_callers(30)
        f.write(stream.getvalue())
        f.write("\n\n")

        # Section 9: Summary statistics
        f.write("SECTION 9: SUMMARY STATISTICS\n")
        f.write("-" * 100 + "\n\n")

        # Calculate summary stats
        total_calls = sum(stat[0] for stat in stats.stats.values())
        total_primitive_calls = sum(stat[1] for stat in stats.stats.values())
        total_functions = len(stats.stats)

        f.write(f"Total function calls: {total_calls:,}\n")
        f.write(f"Total primitive calls: {total_primitive_calls:,}\n")
        f.write(f"Total unique functions: {total_functions:,}\n")
        f.write(f"Total execution time: {total_time:.4f} seconds\n")
        f.write(f"Average time per call: {(total_time / total_calls * 1000000):.2f} microseconds\n")

        f.write("\n" + "=" * 100 + "\n")
        f.write("END OF REPORT\n")
        f.write("=" * 100 + "\n")

    print(f"\nReport saved to: {output_file}")


def main():
    """Main execution function"""
    print("Backtrader Performance Profiling Tool")
    print("=" * 50)
    print()

    # Profile the test
    test_path = r"tests\original_tests\test_strategy_optimized.py"

    try:
        stats, total_time = profile_test(test_path)

        # Generate branch-specific filename
        branch = get_git_branch()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"performance_profile_{branch}_{timestamp}.log"

        # Generate report
        generate_report(stats, total_time, output_file)

        # Also print top 100 to console
        print("\n" + "=" * 60)
        print("TOP 100 FUNCTIONS BY CUMULATIVE TIME:")
        print("=" * 60)
        stats.stream = sys.stdout
        stats.sort_stats("cumulative")
        stats.print_stats(100)

        print("\n" + "=" * 60)
        print("TOP 100 BACKTRADER FUNCTIONS:")
        print("=" * 60)
        stats.stream = sys.stdout
        stats.sort_stats("cumulative")
        stats.print_stats("backtrader", 100)

    except Exception as e:
        print(f"Error during profiling: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
