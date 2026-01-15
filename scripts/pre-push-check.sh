#!/bin/bash
# Pre-push check script for Backtrader
# Run this before pushing to ensure code quality
# Usage: ./scripts/pre-push-check.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "Backtrader Pre-Push Check"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Step 1: Check if required tools are installed
echo "📋 Checking dependencies..."
MISSING_DEPS=""

check_pip_package() {
    python -c "import $1" 2>/dev/null || MISSING_DEPS="$MISSING_DEPS $2"
}

check_pip_package "ruff" "ruff"
check_pip_package "black" "black"
check_pip_package "isort" "isort"
check_pip_package "pytest" "pytest"

if [ -n "$MISSING_DEPS" ]; then
    echo -e "${YELLOW}⚠️  Missing packages:$MISSING_DEPS${NC}"
    echo "Installing missing packages..."
    pip install $MISSING_DEPS
fi
echo -e "${GREEN}✅ Dependencies OK${NC}"
echo ""

# Step 2: Run linting
echo "🔍 Step 1: Running ruff linter..."
if python -m ruff check backtrader/ --fix; then
    echo -e "${GREEN}✅ Linting passed${NC}"
else
    echo -e "${RED}❌ Linting failed${NC}"
    exit 1
fi
echo ""

# Step 3: Check formatting
echo "🎨 Step 2: Checking code format..."
if python -m black --check --line-length 100 backtrader/ 2>/dev/null; then
    echo -e "${GREEN}✅ Formatting OK${NC}"
else
    echo -e "${YELLOW}⚠️  Formatting issues found, auto-fixing...${NC}"
    python -m black --line-length 100 backtrader/
    echo -e "${GREEN}✅ Formatting fixed${NC}"
fi
echo ""

# Step 4: Run tests
echo "🧪 Step 3: Running tests..."
if [ -d "tests" ]; then
    if python -m pytest tests -n auto --tb=short -q; then
        echo -e "${GREEN}✅ All tests passed${NC}"
    else
        echo -e "${RED}❌ Tests failed${NC}"
        echo "Fix the failing tests before pushing."
        exit 1
    fi
else
    echo -e "${YELLOW}⚠️  No tests directory found${NC}"
fi
echo ""

echo "=========================================="
echo -e "${GREEN}✅ All checks passed! Ready to push.${NC}"
echo "=========================================="
