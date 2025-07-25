#!/bin/bash
# Sync script to push to GitHub repository

echo "Syncing with GitHub repository..."

# Add GitHub remote if it doesn't exist
git remote add github https://github.com/cloudQuant/backtrader.git 2>/dev/null || true

# Get the current branch
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Push to GitHub
echo "Pushing branch $BRANCH to GitHub..."
git push github $BRANCH --force

# Push tags if any
echo "Pushing tags to GitHub..."
git push github --tags --force

echo "Sync completed!"