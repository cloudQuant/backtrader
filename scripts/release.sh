#!/bin/bash
# Backtrader Release Script
# Usage: ./scripts/release.sh <version>
# Example: ./scripts/release.sh 1.0.1

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check version argument
VERSION=$1
if [ -z "$VERSION" ]; then
    echo -e "${RED}Error: Version number required${NC}"
    echo "Usage: ./scripts/release.sh <version>"
    echo "Example: ./scripts/release.sh 1.0.1"
    exit 1
fi

# Validate version format (x.y.z)
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo -e "${RED}Error: Invalid version format. Use x.y.z (e.g., 1.0.1)${NC}"
    exit 1
fi

echo -e "${GREEN}📦 Starting release v$VERSION...${NC}"

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo -e "${YELLOW}Warning: You have uncommitted changes${NC}"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Step 1: Update version number
echo -e "${GREEN}[1/6] Updating version to $VERSION...${NC}"
VERSION_FILE="$PROJECT_ROOT/backtrader/version.py"

if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    sed -i '' "s/__version__ = \".*\"/__version__ = \"$VERSION\"/" "$VERSION_FILE"
else
    # Linux
    sed -i "s/__version__ = \".*\"/__version__ = \"$VERSION\"/" "$VERSION_FILE"
fi

# Verify version update
CURRENT_VERSION=$(grep -o '__version__ = "[^"]*"' "$VERSION_FILE" | cut -d'"' -f2)
if [ "$CURRENT_VERSION" != "$VERSION" ]; then
    echo -e "${RED}Error: Failed to update version${NC}"
    exit 1
fi
echo -e "  Version updated to $CURRENT_VERSION"

# Step 2: Run tests (optional)
echo -e "${GREEN}[2/6] Running tests...${NC}"
read -p "Run tests before release? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if command -v pytest &> /dev/null; then
        pytest "$PROJECT_ROOT/backtrader/tests" -x -q --tb=short || {
            echo -e "${RED}Tests failed. Abort release? (y/n)${NC}"
            read -p "" -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                git checkout "$VERSION_FILE"
                exit 1
            fi
        }
    else
        echo -e "${YELLOW}pytest not found, skipping tests${NC}"
    fi
else
    echo "  Skipping tests"
fi

# Step 3: Build package
echo -e "${GREEN}[3/6] Building package...${NC}"
if command -v python &> /dev/null; then
    # Clean old builds
    rm -rf "$PROJECT_ROOT/dist" "$PROJECT_ROOT/build" "$PROJECT_ROOT"/*.egg-info
    
    # Install build tools if needed
    pip install --quiet build twine 2>/dev/null || true
    
    # Build
    python -m build "$PROJECT_ROOT" --outdir "$PROJECT_ROOT/dist"
    
    echo -e "  Built packages:"
    ls -la "$PROJECT_ROOT/dist/"
else
    echo -e "${RED}Python not found${NC}"
    exit 1
fi

# Step 4: Commit and tag
echo -e "${GREEN}[4/6] Committing changes and creating tag...${NC}"
git add "$VERSION_FILE"
git commit -m "chore: release v$VERSION" || echo "  No changes to commit"
git tag -a "v$VERSION" -m "Release v$VERSION"
echo -e "  Created tag v$VERSION"

# Step 5: Push to remotes
echo -e "${GREEN}[5/6] Pushing to remotes...${NC}"

# Get current branch
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo -e "  Current branch: $BRANCH"

# Push to origin (configured with both GitHub and Gitee)
echo -e "  Pushing to origin (GitHub + Gitee)..."
git push origin "$BRANCH" --tags

# Check if push was successful
if [ $? -eq 0 ]; then
    echo -e "${GREEN}  ✓ Pushed to all remotes${NC}"
else
    echo -e "${RED}  ✗ Push failed${NC}"
    exit 1
fi

# Step 6: Upload to PyPI (optional)
echo -e "${GREEN}[6/6] Upload to PyPI...${NC}"
read -p "Upload to PyPI? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if command -v twine &> /dev/null; then
        echo -e "  Uploading to PyPI..."
        twine upload "$PROJECT_ROOT/dist/*"
        echo -e "${GREEN}  ✓ Uploaded to PyPI${NC}"
    else
        echo -e "${YELLOW}  twine not found, skipping PyPI upload${NC}"
        echo "  Install with: pip install twine"
    fi
else
    echo "  Skipping PyPI upload"
fi

# Summary
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Release v$VERSION completed!${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo "Release artifacts:"
echo "  - Git tag: v$VERSION"
echo "  - Packages: dist/"
echo ""
echo "Pushed to:"
echo "  - GitHub: https://github.com/cloudQuant/backtrader"
echo "  - Gitee:  https://gitee.com/yunjinqi/backtrader"
echo ""
echo "Next steps:"
echo "  1. Create GitHub Release at:"
echo "     https://github.com/cloudQuant/backtrader/releases/new?tag=v$VERSION"
echo "  2. Verify PyPI package at:"
echo "     https://pypi.org/project/backtrader/"
