#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Backtrader Master Test Runner
=============================
This script runs comprehensive tests and generates detailed HTML reports.

Features:
- Runs all test suites (original_tests, add_tests, base_functions, funding_rate_examples)
- Generates comprehensive HTML report with pytest-html
- Collects test statistics and summary
- Provides detailed failure analysis
- Tracks test execution time

Usage:
    python run_master_tests.py              # Run tests and generate report (default)
    python run_master_tests.py --analyze    # Only show analysis without running tests
    python run_master_tests.py -a          # Short form for --analyze
"""

import os
import sys
import time
import subprocess
import json
from datetime import datetime
from pathlib import Path


def get_system_info():
    """Collect system information for the report"""
    import platform
    
    info = {
        'Python Version': sys.version.split()[0],
        'Platform': platform.platform(),
        'OS': platform.system(),
        'OS Version': platform.version(),
        'Architecture': platform.machine(),
        'Processor': platform.processor(),
        'Hostname': platform.node(),
    }
    
    # Get installed packages
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'list', '--format', 'json'],
            capture_output=True,
            text=True,
            check=True
        )
        packages = json.loads(result.stdout)
        info['Installed Packages'] = len(packages)
    except:
        info['Installed Packages'] = 'N/A'
    
    return info


def get_backtrader_version():
    """Get backtrader version"""
    try:
        import backtrader as bt
        return bt.__version__
    except:
        return "Unknown"


def get_test_directories():
    """Get all test directories"""
    test_dirs = []
    tests_path = Path('tests')
    
    if tests_path.exists():
        for item in tests_path.iterdir():
            if item.is_dir() and not item.name.startswith('__'):
                # Check if directory contains test files
                test_files = list(item.glob('test_*.py'))
                if test_files:
                    test_dirs.append({
                        'path': str(item),
                        'name': item.name,
                        'test_count': len(test_files)
                    })
    
    return test_dirs


def run_tests(output_file='backtrader_master_tests_report.html'):
    """Run all tests and generate comprehensive report"""
    
    print("=" * 80)
    print("Backtrader Master Test Suite Runner")
    print("=" * 80)
    print()
    
    # Get system info
    print("Collecting system information...")
    sys_info = get_system_info()
    bt_version = get_backtrader_version()
    
    print(f"Python Version: {sys_info['Python Version']}")
    print(f"Platform: {sys_info['Platform']}")
    print(f"Backtrader Version: {bt_version}")
    print()
    
    # Get test directories
    print("Scanning test directories...")
    test_dirs = get_test_directories()
    print(f"Found {len(test_dirs)} test directories:")
    for td in test_dirs:
        print(f"  - {td['name']}: {td['test_count']} test files")
    print()
    
    # Prepare pytest command
    start_time = time.time()
    
    pytest_args = [
        sys.executable, '-m', 'pytest',
        'tests/',
        f'--html={output_file}',
        '--self-contained-html',
        '--tb=short',
        '--verbose',
        '--color=yes',
        '-ra',  # Show summary of all test outcomes
        '--maxfail=1000',  # Don't stop on first failure
        '--tb=line',  # Shorter traceback format
        '--capture=no',  # Show print output
    ]
    
    # Add parallel execution if pytest-xdist is available
    try:
        import xdist
        pytest_args.extend(['-n', '12'])  # Use 12 CPU cores
        print("Running tests in parallel mode with 12 workers (pytest-xdist detected)")
    except ImportError:
        print("Running tests in sequential mode (pytest-xdist not available)")
    
    print()
    print("Starting test execution...")
    print("-" * 80)
    
    # Run pytest
    result = subprocess.run(pytest_args)
    
    end_time = time.time()
    duration = end_time - start_time
    
    print("-" * 80)
    print()
    print("=" * 80)
    print("Test Execution Summary")
    print("=" * 80)
    print(f"Total execution time: {duration:.2f} seconds ({duration/60:.2f} minutes)")
    print(f"HTML Report: {output_file}")
    print()
    
    if result.returncode == 0:
        print("✓ All tests passed!")
    else:
        print(f"✗ Some tests failed (exit code: {result.returncode})")
        print(f"  Please check {output_file} for details")
    
    print()
    print("=" * 80)
    
    return result.returncode


def analyze_existing_report():
    """Analyze why report.html might not be generating"""
    
    print()
    print("=" * 80)
    print("Analyzing Report Generation Issues")
    print("=" * 80)
    print()
    
    findings = []
    
    # Check if pytest-html is installed
    try:
        import pytest_html
        findings.append(f"✓ pytest-html is installed (version {pytest_html.__version__})")
    except ImportError:
        findings.append("✗ pytest-html is NOT installed")
        findings.append("  Install it with: pip install pytest-html")
    
    # Check for pytest configuration
    config_files = ['pytest.ini', 'setup.cfg', 'pyproject.toml']
    found_config = False
    for config_file in config_files:
        if Path(config_file).exists():
            findings.append(f"✓ Found pytest configuration: {config_file}")
            found_config = True
            
            # Check if HTML report is configured
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if '--html' in content or 'html' in content.lower():
                    findings.append(f"  ✓ HTML reporting is configured in {config_file}")
                else:
                    findings.append(f"  ℹ No HTML reporting configuration found in {config_file}")
    
    if not found_config:
        findings.append("ℹ No pytest configuration files found (pytest.ini, setup.cfg)")
    
    # Check if report.html exists
    if Path('report.html').exists():
        stat = Path('report.html').stat()
        mod_time = datetime.fromtimestamp(stat.st_mtime)
        findings.append(f"✓ report.html exists (last modified: {mod_time})")
        findings.append(f"  File size: {stat.st_size:,} bytes")
    else:
        findings.append("✗ report.html does not exist")
    
    # Check test execution scripts
    test_scripts = [
        'test_python_versions_simple.bat',
        'test_python_versions_simple.sh'
    ]
    for script in test_scripts:
        if Path(script).exists():
            findings.append(f"✓ Found test script: {script}")
            with open(script, 'r', encoding='utf-8') as f:
                content = f.read()
                if '--html' in content:
                    findings.append(f"  ✓ {script} includes HTML report generation")
                else:
                    findings.append(f"  ✗ {script} does NOT generate HTML reports")
                    findings.append(f"    Add '--html=report.html' to pytest command")
    
    # Print findings
    for finding in findings:
        print(finding)
    
    print()
    print("Summary:")
    print("-" * 80)
    print("The existing report.html was generated by pytest-html, but it's not")
    print("being automatically generated because:")
    print()
    print("1. The test scripts (test_python_versions_simple.bat/sh) don't include")
    print("   the --html flag in their pytest commands")
    print()
    print("2. pyproject.toml has pytest configuration but doesn't specify HTML")
    print("   output by default")
    print()
    print("3. To generate reports automatically, you need to:")
    print("   - Run pytest with '--html=report.html --self-contained-html'")
    print("   - Or add 'addopts = --html=report.html' to [tool.pytest.ini_options]")
    print("   - Or use this script: python run_master_tests.py")
    print()
    print("=" * 80)
    print()


def main():
    """Main entry point"""
    
    # Check if --analyze flag is provided
    if '--analyze' in sys.argv or '--analysis' in sys.argv or '-a' in sys.argv:
        # Only run analysis without executing tests
        analyze_existing_report()
        print()
        print("Analysis complete. To run tests, execute: python run_master_tests.py")
        sys.exit(0)
    
    # Default behavior: run tests directly and generate report
    print("Starting Backtrader Master Test Suite...")
    print("(Use 'python run_master_tests.py --analyze' to only see analysis)")
    print()
    
    exit_code = run_tests()
    
    print()
    print("To view detailed analysis of report generation, run:")
    print("  python run_master_tests.py --analyze")
    
    sys.exit(exit_code)


if __name__ == '__main__':
    main()

