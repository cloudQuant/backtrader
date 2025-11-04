#!/bin/bash
# Unix shell script to install package and run pytest
# Output is logged to test_results.log

set -o pipefail

# Set UTF-8 locale to prevent encoding issues
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONIOENCODING=utf-8

LOG_FILE="test_results.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Initialize log file
{
    echo "============================================"
    echo "Test Run Started at: $TIMESTAMP"
    echo "============================================"
    echo ""
} > "$LOG_FILE"

echo "Installing package..."
{
    echo "[INSTALL] pip install -U ."
    echo ""
} >> "$LOG_FILE"

# Install package
if ! pip install -U . >> "$LOG_FILE" 2>&1; then
    echo "ERROR: Package installation failed!" | tee -a "$LOG_FILE"
    exit 1
fi

{
    echo ""
    echo "============================================"
    echo "Running pytest tests -n 12"
    echo "============================================"
    echo ""
} >> "$LOG_FILE"

echo "Running tests..."

# Run pytest with verbose output and capture results
pytest tests -n 12 -v --tb=short >> "$LOG_FILE" 2>&1
PYTEST_EXIT_CODE=$?

{
    echo ""
    echo "============================================"
    echo "Test Summary"
    echo "============================================"
} >> "$LOG_FILE"

# Extract failed count from pytest summary line
FAILED_COUNT=0
SUMMARY_LINE=$(grep -E "[0-9]+ failed.*[0-9]+ passed" "$LOG_FILE" | tail -1 || echo "")

if [ -n "$SUMMARY_LINE" ]; then
    # Extract number before "failed" using sed
    FAILED_COUNT=$(echo "$SUMMARY_LINE" | sed -n 's/.*[^0-9]\([0-9]\+\) failed.*/\1/p')
    # If extraction failed, try another pattern
    if [ -z "$FAILED_COUNT" ]; then
        FAILED_COUNT=$(echo "$SUMMARY_LINE" | sed -n 's/^.*=\+ \([0-9]\+\) failed.*/\1/p')
    fi
    # Default to 0 if still empty
    if [ -z "$FAILED_COUNT" ]; then
        FAILED_COUNT=0
    fi
fi

# Extract unique failed test case names
FAILED_TESTS=$(grep "FAILED tests.*::" "$LOG_FILE" | sed -n 's/.*FAILED \(tests[^ ]*\).*/\1/p' | sort -u || true)

{
    echo ""
    echo "Total Failed Tests: $FAILED_COUNT"
    echo ""
} >> "$LOG_FILE"

if [ "$FAILED_COUNT" -gt 0 ] && [ -n "$FAILED_TESTS" ]; then
    {
        echo "Failed Test Cases:"
        echo "-------------------"
        echo "$FAILED_TESTS"
        echo ""
    } >> "$LOG_FILE"
fi

END_TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
{
    echo "============================================"
    echo "Test Run Ended at: $END_TIMESTAMP"
    echo "============================================"
} >> "$LOG_FILE"

# Output results to console
echo ""
echo "============================================"
echo "Test Execution Complete"
echo "============================================"
echo "Log file: $LOG_FILE"
echo "Failed Tests: $FAILED_COUNT"
echo ""

if [ "$FAILED_COUNT" -gt 0 ] && [ -n "$FAILED_TESTS" ]; then
    echo "Failed Test Cases:"
    echo "-------------------"
    echo "$FAILED_TESTS"
    echo ""
fi

# Exit with pytest exit code
exit $PYTEST_EXIT_CODE
