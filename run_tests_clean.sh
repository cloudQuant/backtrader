#!/bin/bash
# =============================================================================
# Enhanced Test Runner Script for Backtrader
# =============================================================================
# Description: Run pytest with parallel execution, timeout, and colored output
# Usage: ./run_tests_clean.sh [options]
# Options:
#   -n NUM    Number of parallel workers (default: 8)
#   -t SEC    Timeout per test in seconds (default: 45)
#   -p PATH   Test path (default: tests)
#   -k EXPR   Only run tests matching expression
#   -v        Verbose output
#   -h        Show this help
# =============================================================================

set -o pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Default configuration
WORKERS=8
TIMEOUT=45
TEST_PATH="tests"
VERBOSE=""
FILTER=""

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

# Print header
echo -e "${BLUE}============================================================${NC}"
echo -e "${CYAN}Backtrader Test Runner${NC}"
echo -e "${BLUE}============================================================${NC}"
echo -e "Test Path:    ${YELLOW}$TEST_PATH${NC}"
echo -e "Workers:      ${YELLOW}$WORKERS${NC}"
echo -e "Timeout:      ${YELLOW}${TIMEOUT}s${NC} per test"
echo -e "Filter:       ${YELLOW}${FILTER:-none}${NC}"
echo -e "${BLUE}============================================================${NC}"

# Create temp file to capture output
TEMP_OUTPUT=$(mktemp)
trap "rm -f $TEMP_OUTPUT" EXIT

# Execute tests
START_TIME=$(date +%s)

python -m pytest "$TEST_PATH" \
    -n "$WORKERS" \
    --timeout="$TIMEOUT" \
    --timeout-method=thread \
    --tb=short \
    --strict-markers \
    --disable-warnings \
    --color=yes \
    -q \
    $VERBOSE \
    $FILTER 2>&1 | tee "$TEMP_OUTPUT"

EXIT_CODE=${PIPESTATUS[0]}
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Extract statistics
FAILED_TESTS=$(grep -E "FAILED.*::" "$TEMP_OUTPUT" 2>/dev/null | wc -l | xargs)
TIMEOUT_TESTS=$(grep "Timeout >" "$TEMP_OUTPUT" 2>/dev/null | wc -l | xargs)
PASSED_TESTS=$(grep -oE "[0-9]+ passed" "$TEMP_OUTPUT" 2>/dev/null | head -1 | grep -oE "[0-9]+" | head -1)
FAILED_TESTS=${FAILED_TESTS:-0}
TIMEOUT_TESTS=${TIMEOUT_TESTS:-0}
PASSED_TESTS=${PASSED_TESTS:-0}

# Print summary
echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${CYAN}Test Summary${NC}"
echo -e "${BLUE}============================================================${NC}"
echo -e "Duration:     ${YELLOW}${DURATION}s${NC}"
echo -e "Exit Code:    ${YELLOW}$EXIT_CODE${NC}"
echo -e "${BLUE}------------------------------------------------------------${NC}"
echo -e "Passed:       ${GREEN}$PASSED_TESTS${NC}"
echo -e "Failed:       ${RED}$FAILED_TESTS${NC}"
echo -e "Timeout:      ${YELLOW}$TIMEOUT_TESTS${NC}"
echo -e "${BLUE}------------------------------------------------------------${NC}"

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "Status:       ${GREEN}✅ ALL TESTS PASSED${NC}"
elif [ $EXIT_CODE -eq 1 ]; then
    echo -e "Status:       ${RED}❌ SOME TESTS FAILED${NC}"
elif [ $EXIT_CODE -eq 2 ]; then
    echo -e "Status:       ${YELLOW}⚠️  TEST EXECUTION INTERRUPTED${NC}"
elif [ $EXIT_CODE -eq 5 ]; then
    echo -e "Status:       ${YELLOW}⚠️  NO TESTS COLLECTED${NC}"
else
    echo -e "Status:       ${RED}❌ ERROR (code: $EXIT_CODE)${NC}"
fi

# Show failed tests if any
if [ "$FAILED_TESTS" -gt 0 ]; then
    echo ""
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${RED}Failed Tests:${NC}"
    echo -e "${BLUE}============================================================${NC}"
    grep -E "FAILED.*::" "$TEMP_OUTPUT" | sed 's/^/  /'
fi

# Show timeout tests if any
if [ "$TIMEOUT_TESTS" -gt 0 ]; then
    echo ""
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${YELLOW}Timeout Tests (>${TIMEOUT}s):${NC}"
    echo -e "${BLUE}============================================================${NC}"
    grep -B5 "Timeout >" "$TEMP_OUTPUT" | grep -E "::test_" | sed 's/^/  /' | sort -u
fi

echo -e "${BLUE}============================================================${NC}"
exit $EXIT_CODE
