#!/usr/bin/env python
"""
Backtrader Selected Tests Runner
=================================
Run specified test directories and generate HTML report.

Test directories:
- tests/add_tests
- tests/original_tests
- tests/base_functions

Configuration:
- 12-core parallel execution
- Generate backtrader_remove_metaprogramming_report.html
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def check_test_directories():
    """Check if test directories exist."""
    test_dirs = ["tests/add_tests", "tests/original_tests", "tests/base_functions"]

    missing_dirs = []
    found_dirs = []

    for test_dir in test_dirs:
        if Path(test_dir).exists():
            test_files = list(Path(test_dir).glob("test_*.py"))
            found_dirs.append({"path": test_dir, "count": len(test_files)})
        else:
            missing_dirs.append(test_dir)

    return found_dirs, missing_dirs


def run_tests():
    """Run tests and generate report."""

    print("=" * 80)
    print("Backtrader Selected Tests Runner")
    print("=" * 80)
    print()

    # Record script start time
    script_start_time = time.time()
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Check test directories
    print("Checking test directories...")
    found_dirs, missing_dirs = check_test_directories()

    if missing_dirs:
        print()
        print("⚠️  Warning: The following directories do not exist:")
        for missing in missing_dirs:
            print(f"   - {missing}")
        print()

    if not found_dirs:
        print("❌ Error: No test directories found!")
        return 1

    print()
    print("Found the following test directories:")
    total_files = 0
    for dir_info in found_dirs:
        print(f"   ✓ {dir_info['path']}: {dir_info['count']} test files")
        total_files += dir_info["count"]
    print(f"\nTotal: {total_files} test files")
    print()

    # Prepare test paths
    test_paths = [d["path"] for d in found_dirs]

    # Prepare pytest command
    output_file = "backtrader_remove_metaprogramming_report.html"

    pytest_args = [sys.executable, "-m", "pytest"]

    # Add test paths
    pytest_args.extend(test_paths)

    # Add report parameters
    pytest_args.extend(
        [
            f"--html={output_file}",
            "--self-contained-html",
            "--tb=short",
            "--verbose",
            "--color=yes",
            "-ra",  # Show all test result summary
            "--maxfail=1000",  # Don't stop on first failure
        ]
    )

    # Add parallel execution parameters
    try:
        import xdist

        pytest_args.extend(["-n", "12"])  # Use 12 cores
        print("✓ Using 12-core parallel execution (pytest-xdist installed)")
    except ImportError:
        print("⚠️  pytest-xdist not installed, will use serial execution")
        print("   Install with: pip install pytest-xdist")

    print()
    print("-" * 80)
    print("Starting test execution...")
    print(f"Test start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 80)

    # Record pytest start time (wall clock time)
    pytest_start_time = time.time()

    # Run pytest
    result = subprocess.run(pytest_args)

    # Record pytest end time
    pytest_end_time = time.time()
    pytest_duration = pytest_end_time - pytest_start_time

    # Calculate total time (including preparation)
    total_duration = pytest_end_time - script_start_time

    print()
    print("-" * 80)
    print()
    print("=" * 80)
    print("Test execution completed")
    print("=" * 80)
    print()
    print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print(f"⏱️  Test execution time (wall clock): {pytest_duration:.2f} seconds ({pytest_duration/60:.2f} minutes)")
    print(f"📊 Total time (including prep): {total_duration:.2f} seconds ({total_duration/60:.2f} minutes)")
    print(f"📄 HTML report: {output_file}")
    print()

    # Write timing info to separate file for later analysis
    timing_info = {
        "script_start": datetime.fromtimestamp(script_start_time).strftime("%Y-%m-%d %H:%M:%S"),
        "pytest_start": datetime.fromtimestamp(pytest_start_time).strftime("%Y-%m-%d %H:%M:%S"),
        "pytest_end": datetime.fromtimestamp(pytest_end_time).strftime("%Y-%m-%d %H:%M:%S"),
        "pytest_duration_seconds": pytest_duration,
        "total_duration_seconds": total_duration,
        "report_file": output_file,
        "test_directories": test_paths,
        "parallel_workers": 12,
        "timestamp": datetime.now().isoformat(),
    }

    timing_file = output_file.replace(".html", "_timing.json")
    import json

    with open(timing_file, "w", encoding="utf-8") as f:
        json.dump(timing_info, f, indent=2, ensure_ascii=False)

    print(f"⏰ Timing info saved: {timing_file}")
    print()

    if result.returncode == 0:
        print("✓ All tests passed!")
        print()
        print(f"View report:")
        print(f"  Double-click to open: {output_file}")
        print(f"  Or open in browser: file:///{Path(output_file).absolute()}")
    else:
        print(f"✗ Some tests failed (exit code: {result.returncode})")
        print()
        print(f"Please see {output_file} for details")

    print()
    print("=" * 80)

    return result.returncode


def show_info():
    """Display test information."""

    print()
    print("=" * 80)
    print("Test Configuration Information")
    print("=" * 80)
    print()
    print("Test directories:")
    print("  - tests/add_tests       (New feature tests)")
    print("  - tests/original_tests  (Original core tests)")
    print("  - tests/base_functions  (Basic function tests)")
    print()
    print("Parallel configuration:")
    print("  - 12-core parallel execution")
    print()
    print("Report output:")
    print("  - backtrader_remove_metaprogramming_report.html")
    print()
    print("Python version:")
    print(f"  - {sys.version.split()[0]}")
    print()

    # Check directories
    found_dirs, missing_dirs = check_test_directories()

    if found_dirs:
        print("Test statistics:")
        for dir_info in found_dirs:
            print(f"  - {dir_info['path']}: {dir_info['count']} test files")

    print()
    print("=" * 80)
    print()


def main():
    """Main entry point."""

    # Check command line arguments
    if "--info" in sys.argv or "-i" in sys.argv:
        show_info()
        return 0

    # Run tests
    return run_tests()


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print()
        print()
        print("Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"❌ Error occurred: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
