#!/usr/bin/env python3
"""Test Runner Script for Backtrader.

This module provides a command-line interface for running pytest with parallel
execution and per-test timeout capabilities. It is designed to efficiently run
the Backtrader test suite with configurable worker counts and timeout limits.

The script builds and executes pytest commands with the following features:
    - Parallel test execution using pytest-xdist
    - Per-test timeout using pytest-timeout
    - Configurable test filtering with -k flag
    - Colored output and formatted summary

Example:
    Run all tests with 4 parallel workers and 30s timeout::

        python run_tests_with_timeout.py -n 4 -t 30

    Run only strategy tests with verbose output::

        python run_tests_with_timeout.py -p tests/strategies -k "rsi" -v

Attributes:
    None (module-level only)
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def parse_args():
    """Parse command-line arguments for the test runner.

    Creates an argument parser with options for configuring test execution
    parameters including worker count, timeout, test path, and filtering.

    Returns:
        argparse.Namespace: Parsed command-line arguments with the following
            attributes:
            - workers (int): Number of parallel workers for test execution.
            - timeout (int): Timeout in seconds for each test.
            - path (str): Path to the test directory or file.
            - filter (str): Keyword expression for filtering tests.
            - verbose (bool): Whether to enable verbose output.

    Example:
        >>> args = parse_args()
        >>> print(args.workers)
        8
    """
    parser = argparse.ArgumentParser(
        description="Run pytest with parallel execution and timeout",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-n",
        "--workers",
        type=int,
        default=8,
        help="Number of parallel workers (default: 8)"
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=45,
        help="Timeout per test in seconds (default: 45)"
    )
    parser.add_argument(
        "-p",
        "--path",
        default="tests",
        help="Test path (default: tests)"
    )
    parser.add_argument(
        "-k",
        "--filter",
        default="",
        help="Only run tests matching expression"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output"
    )
    return parser.parse_args()


def main():
    """Main entry point for the test runner script.

    This function orchestrates the test execution process:
        1. Parses command-line arguments
        2. Changes to the script directory
        3. Builds the pytest command with appropriate options
        4. Displays configuration header
        5. Executes the tests
        6. Displays formatted summary with timing and status

    Returns:
        int: Exit code indicating test result status:
            - 0: All tests passed
            - 1: Some tests failed
            - 2: Test execution interrupted by user
            - 5: No tests collected
            - Other: Error occurred

    Raises:
        KeyboardInterrupt: When the user interrupts test execution with Ctrl+C.
            This is caught and handled gracefully with exit code 2.

    Example:
        >>> exit_code = main()
        >>> print(f"Tests completed with exit code: {exit_code}")
    """
    args = parse_args()

    # Change to script directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    # Build pytest command
    cmd = [
        "python",
        "-m",
        "pytest",
        args.path,
        "-n",
        str(args.workers),
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
        print("\nTest execution interrupted by user.")
        exit_code = 2
    except Exception as e:
        print(f"Error running pytest: {e}")
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
        0: "ALL TESTS PASSED",
        1: "SOME TESTS FAILED",
        2: "TEST EXECUTION INTERRUPTED",
        5: "NO TESTS COLLECTED",
    }
    status = status_map.get(exit_code, f"ERROR (code: {exit_code})")
    print(f"Status:       {status}")
    print("=" * 60)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
