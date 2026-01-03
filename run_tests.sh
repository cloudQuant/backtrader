#!/bin/bash
# =============================================================================
# Test Runner Script for Backtrader
# =============================================================================
# Description: Run pytest with parallel execution and per-test timeout
# Usage: ./run_tests.sh [options]
# Options:
#   -n NUM    Number of parallel workers (default: 8)
#   -t SEC    Timeout per test in seconds (default: 45)
#   -p PATH   Test path (default: tests)
#   -k EXPR   Only run tests matching expression
#   -v        Verbose output
#   -h        Show this help
# =============================================================================

set -o pipefail

# Default configuration
WORKERS=8
TIMEOUT=45
TEST_PATH="tests"
VERBOSE=""
FILTER=""
EXTRA_ARGS=""

# Parse command line arguments
while getopts "n:t:p:k:vh" opt; do
    case $opt in
        n) WORKERS="$OPTARG" ;;
        t) TIMEOUT="$OPTARG" ;;
        p) TEST_PATH="$OPTARG" ;;
        k) FILTER="-k $OPTARG" ;;
        v) VERBOSE="-v" ;;
        h)
            head -15 "$0" | tail -12
            exit 0
            ;;
        \?) echo "Invalid option: -$OPTARG" >&2; exit 1 ;;
    esac
done

# Ensure we're in the correct directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Print configuration
echo "============================================================"
echo "Backtrader Test Runner"
echo "============================================================"
echo "Test Path:    $TEST_PATH"
echo "Workers:      $WORKERS"
echo "Timeout:      ${TIMEOUT}s per test"
echo "Filter:       ${FILTER:-none}"
echo "============================================================"

# Build pytest command
PYTEST_CMD="python -m pytest $TEST_PATH \
    -n $WORKERS \
    --timeout=$TIMEOUT \
    --timeout-method=thread \
    --tb=short \
    --strict-markers \
    -q \
    $VERBOSE \
    $FILTER \
    $EXTRA_ARGS"

echo "Running: $PYTEST_CMD"
echo "============================================================"

# Execute tests
START_TIME=$(date +%s)
eval "$PYTEST_CMD"
EXIT_CODE=$?
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Print summary
echo ""
echo "============================================================"
echo "Test Summary"
echo "============================================================"
echo "Duration:     ${DURATION}s"
echo "Exit Code:    $EXIT_CODE"

if [ $EXIT_CODE -eq 0 ]; then
    echo "Status:       ✅ ALL TESTS PASSED"
elif [ $EXIT_CODE -eq 1 ]; then
    echo "Status:       ❌ SOME TESTS FAILED"
elif [ $EXIT_CODE -eq 2 ]; then
    echo "Status:       ⚠️  TEST EXECUTION INTERRUPTED"
elif [ $EXIT_CODE -eq 5 ]; then
    echo "Status:       ⚠️  NO TESTS COLLECTED"
else
    echo "Status:       ❌ ERROR (code: $EXIT_CODE)"
fi

echo "============================================================"
exit $EXIT_CODE
