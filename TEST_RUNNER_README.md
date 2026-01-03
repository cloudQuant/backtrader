# Backtrader Test Runner

Scripts for running pytest with parallel execution and per-test timeout.

## Quick Start

```bash
# Run all tests with default settings (8 workers, 45s timeout)
./run_tests.sh

# Run with colored output
./run_tests_clean.sh

# Run specific test directory
./run_tests.sh -p tests/strategies

# Run with custom timeout
./run_tests.sh -t 60

# Run with filter
./run_tests.sh -k "test_sma"
```

## Scripts

| Script | Description |
|--------|-------------|
| `run_tests.sh` | Basic test runner |
| `run_tests_clean.sh` | Enhanced with colored output |
| `run_tests_with_timeout.py` | Python version |

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `-n NUM` | Number of parallel workers | 8 |
| `-t SEC` | Timeout per test (seconds) | 45 |
| `-p PATH` | Test path | tests |
| `-k EXPR` | Filter expression | - |
| `-v` | Verbose output | off |
| `-h` | Show help | - |

## Configuration

**Default Settings:**
- **Workers:** 8 parallel processes
- **Timeout:** 45 seconds per test
- **Timeout Method:** thread-based
- **Traceback:** short format

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All tests passed |
| 1 | Some tests failed |
| 2 | Execution interrupted |
| 5 | No tests collected |

## Requirements

```bash
pip install pytest-xdist pytest-timeout
```

## Examples

```bash
# Run strategy tests only
./run_tests.sh -p tests/strategies

# Run with 4 workers and 60s timeout
./run_tests.sh -n 4 -t 60

# Run verbose with filter
./run_tests.sh -v -k "test_macd"

# Python version with options
python run_tests_with_timeout.py -n 4 -t 60 -p tests/strategies
```
