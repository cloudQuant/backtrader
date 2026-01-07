#!/usr/bin/env python3
"""
Test Runner Script for Backtrader
=================================
Run pytest with parallel execution and per-test timeout.

Usage:
    python run_tests_with_timeout.py [options]

Options:
    -n NUM    Number of parallel workers (default: 8)
    -t SEC    Timeout per test in seconds (default: 45)
    -p PATH   Test path (default: tests)
    -k EXPR   Only run tests matching expression
    -v        Verbose output
    -h        Show this help
"""

import argparse
import subprocess
import sys
import os
import time
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run pytest with parallel execution and timeout",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-n", "--workers", type=int, default=8,
                        help="Number of parallel workers (default: 8)")
    parser.add_argument("-t", "--timeout", type=int, default=45,
                        help="Timeout per test in seconds (default: 45)")
    parser.add_argument("-p", "--path", default="tests",
                        help="Test path (default: tests)")
    parser.add_argument("-k", "--filter", default="",
                        help="Only run tests matching expression")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Verbose output")
    return parser.parse_args()


def main():
    args = parse_args()
    
    # Change to script directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    # Build pytest command
    cmd = [
        "python", "-m", "pytest",
        args.path,
        "-n", str(args.workers),
        f"--timeout={args.timeout}",
        "--timeout-method=thread",
        "--tb=short",
        "--strict-markers",
        "-q",
    ]
    
    if args.verbose:
        cmd.append("-v")
    
    if args.filter:
        cmd.extend(["-k", args.filter])
    
    # Print header
    print("=" * 60)
    print("Backtrader Test Runner")
    print("=" * 60)
    print(f"Test Path:    {args.path}")
    print(f"Workers:      {args.workers}")
    print(f"Timeout:      {args.timeout}s per test")
    print(f"Filter:       {args.filter or 'none'}")
    print("=" * 60)
    print(f"Running: {' '.join(cmd)}")
    print("=" * 60)
    
    # Execute tests
    start_time = time.time()
    
    try:
        result = subprocess.run(cmd, check=False)
        exit_code = result.returncode
    except KeyboardInterrupt:
        print("\n⚠️  Test execution interrupted by user.")
        exit_code = 2
    except Exception as e:
        print(f"❌ Error running pytest: {e}")
        exit_code = 1
    
    duration = int(time.time() - start_time)
    
    # Print summary
    print("")
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"Duration:     {duration}s")
    print(f"Exit Code:    {exit_code}")
    
    status_map = {
        0: "✅ ALL TESTS PASSED",
        1: "❌ SOME TESTS FAILED",
        2: "⚠️  TEST EXECUTION INTERRUPTED",
        5: "⚠️  NO TESTS COLLECTED",
    }
    status = status_map.get(exit_code, f"❌ ERROR (code: {exit_code})")
    print(f"Status:       {status}")
    print("=" * 60)
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
