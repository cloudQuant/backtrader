---
title: Release Workflow Guide
description: Guidelines for creating Backtrader releases
---

# Release Workflow Guide

This document describes the complete release process for the Backtrader project, including version management, pre-release requirements, and post-release tasks.

## Version Management

### Semantic Versioning

Backtrader follows [Semantic Versioning 2.0.0](https://semver.org/):

```
MAJOR.MINOR.PATCH

Examples:
  - 1.0.0  → Initial stable release
  - 1.1.0  → New features (backward compatible)
  - 1.1.1  → Bug fixes only
  - 2.0.0  → Breaking API changes
```

### Version Number Rules

| Type | Change Example | Version Bump |
|------|---------------|--------------|
| **MAJOR** | Removing metaclasses, API redesign | 1.x.x → 2.0.0 |
| **MINOR** | New CCXT broker, Plotly charts | 1.0.x → 1.1.0 |
| **PATCH** | Bug fixes, typo corrections | 1.1.0 → 1.1.1 |

### Determining Version Type

**Bump MAJOR when:**
- Removing or renaming public APIs
- Changing behavior of core classes (Cerebro, Strategy, Indicator)
- Modifying required dependencies with breaking changes
- Reorganizing package structure

**Bump MINOR when:**
- Adding new indicators, feeds, brokers, or analyzers
- New optional features that don't affect existing code
- Adding new optional dependencies
- Performance improvements without API changes

**Bump PATCH when:**
- Fixing bugs that don't change API
- Updating documentation
- Adding tests
- Minor internal refactoring

## Branching Strategy

```
dev (main development branch)
  ├── Active development
  ├── All feature branches merge here
  └── Release candidates branch from here

master (stable releases)
  ├── Production-ready code only
  ├── Merges from dev via release PR
  └── Tags created from commits here

feature/* (short-lived branches)
  ├── Created from dev
  └── Merge back to dev via PR

release/* (preparation branches)
  ├── Created from dev for final testing
  └── Merge to both dev and master after release
```

### Release Branch Lifecycle

```bash
# 1. Create release branch from dev
git checkout dev
git pull origin dev
git checkout -b release/1.1.0

# 2. Finalize version updates and testing
# (see Pre-Release Checklist below)

# 3. Merge release to master
git checkout master
git merge --no-ff release/1.1.0
git tag -a v1.1.0 -m "Release v1.1.0"

# 4. Merge release back to dev
git checkout dev
git merge --no-ff release/1.1.0

# 5. Push all changes
git push origin master dev --tags
```

## Pre-Release Checklist

Complete all items before creating a release:

### 1. Code Quality

```bash
# Format check
make format-check

# Linting
make lint

# Type checking (optional but recommended)
make type-check

# Security checks
make security
```

### 2. Testing

```bash
# Run full test suite
pytest tests/ -n 4 -v --tb=short

# Run with coverage
pytest tests/ --cov=backtrader --cov-report=term-missing:skip-covered

# Run integration tests (requires testnet credentials)
pytest tests/integration/ -m integration -v

# Run P0/P1 critical tests only
pytest tests/ -v -m "priority_p0 or priority_p1"
```

**Minimum Requirements:**
- All P0 tests must pass
- No regressions in existing tests
- Coverage should not decrease from previous release

### 3. Documentation

```bash
# Generate documentation
make docs

# Verify docs build without errors
make docs-en
make docs-zh
```

**Verify:**
- [ ] All new features have documentation
- [ ] API changes are documented
- [ ] Migration guide for breaking changes
- [ ] Examples are up to date

### 4. Version Updates

Update `backtrader/version.py`:

```python
# Before
__version__ = "1.0.0"

# After (example for minor release)
__version__ = "1.1.0"
```

Verify version is accessible:

```bash
python -c "import backtrader; print(backtrader.__version__)"
# Should output: 1.1.0
```

### 5. CHANGELOG.md

Update `CHANGELOG.md` following [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
## [1.1.0] - 2026-03-01

### Added
- CCXT WebSocket support for real-time order updates
- Plotly interactive charting module
- Funding rate data feed for perpetual futures

### Changed
- 45% performance improvement through metaclass removal
- Cython-accelerated time series calculations
- Updated minimum numpy version to 1.20.0

### Fixed
- Order-not-found handling in CCXTBroker.cancel()
- WebSocket reconnection after network interruption
- Memory leak in long-running backtests

### Deprecated
- `matplotlib` plotting (will be removed in 2.0.0)

### Removed
- Legacy `MetaStrategy` metaclass
- Python 3.7 support

### Security
- Rate limit awareness for CCXT API calls
```

## Release Procedure

### Step 1: Final Verification

```bash
# Ensure you're on the release branch
git checkout release/1.1.0

# Pull latest changes
git pull origin release/1.1.0

# Run pre-release checks
make clean
make test-coverage
make docs
make quality-check
```

### Step 2: Update Files

```bash
# Update version in backtrader/version.py
vim backtrader/version.py

# Update CHANGELOG.md with release date
vim CHANGELOG.md

# Commit changes
git add backtrader/version.py CHANGELOG.md
git commit -m "chore: prepare release v1.1.0"
```

### Step 3: Build Distribution Packages

```bash
# Clean previous builds
make clean

# Build source and wheel distributions
python -m build

# Verify packages were created
ls -lh dist/
# Expected output:
# backtrader-1.1.0.tar.gz
# backtrader-1.1.0-py3-none-any.whl
```

### Step 4: Test Distribution

```bash
# Create virtual environment for testing
python -m venv /tmp/test-env
source /tmp/test-env/bin/activate

# Install from wheel
pip install dist/backtrader-1.1.0-py3-none-any.whl

# Verify installation
python -c "import backtrader; print(backtrader.__version__)"

# Run basic smoke test
python -c "
import backtrader as bt
cerebro = bt.Cerebro()
print('Backtrader installed successfully')
"

# Cleanup
deactivate
rm -rf /tmp/test-env
```

### Step 5: Merge to Master

```bash
# Checkout master
git checkout master
git pull origin master

# Merge release branch
git merge --no-ff release/1.1.0 -m "Merge release/1.1.0 into master"

# Create annotated tag
git tag -a v1.1.0 -m "Release v1.1.0

Features:
- CCXT WebSocket support
- Plotly interactive charts
- 45% performance improvement

See CHANGELOG.md for full details."
```

### Step 6: Push and Publish

```bash
# Push master and tags
git push origin master
git push origin v1.1.0

# Merge release back to dev
git checkout dev
git merge --no-ff release/1.1.0 -m "Merge release/1.1.0 back to dev"
git push origin dev

# Publish to PyPI (optional, for public releases)
twine upload dist/*
```

**Note:** PyPI publishing requires:
- Registered PyPI account
- `twine` installed
- API token in `~/.pypirc` or environment variable

## PyPI Publishing

### First-Time Setup

```bash
# Install build tools
pip install build twine

# Create API token at https://pypi.org/manage/account/token/
# Store in ~/.pypirc:
[pypi]
username = __token__
password = pypi-...your-token-here...
```

### Publishing Command

```bash
# Build distributions
python -m build

# Check package description
twine check dist/*

# Upload to PyPI (test first)
twine upload --repository testpypi dist/*

# If test looks good, upload to production
twine upload dist/*
```

### Verify PyPI Release

```bash
# Install from PyPI
pip install backtrader==1.1.0

# Verify version
python -c "import backtrader; print(backtrader.__version__)"
```

## GitHub Release

### Creating via Web UI

1. Go to https://github.com/cloudQuant/backtrader/releases
2. Click "Draft a new release"
3. Choose tag: `v1.1.0`
4. Title: `v1.1.0: Release Summary`
5. Description template (see below)
6. Attach built binaries (optional)
7. Click "Publish release"

### Release Description Template

```markdown
## Backtrader v1.1.0 Release

### Highlights

- **CCXT WebSocket**: Real-time order updates with automatic reconnection
- **Plotly Charts**: Interactive visualization with 100k+ data points
- **Performance**: 45% faster execution through metaclass removal

### What's New

#### Added
- CCXT WebSocket manager with shared connections
- Plotly and Bokeh plotting modules
- Funding rate data feed for perpetual futures
- Threaded order manager for async execution

#### Changed
- Removed all metaclasses from core codebase
- Cython acceleration for time series calculations
- Minimum Python version: 3.8+
- Minimum numpy version: 1.20.0

#### Fixed
- Order-not-found errors in CCXT broker
- WebSocket reconnection after network issues
- Memory leaks in long-running backtests

### Migration Guide

If you're upgrading from v1.0.0:

1. Update imports: `from backtrader.plot import Plotly` (new module)
2. Review CCXT configuration for new WebSocket features
3. Recompile Cython extensions: `cd backtrader && python compile_cython_numba_files.py`

### Installation

```bash
pip install backtrader==1.1.0
```

### Documentation

- [User Guide](https://cloudquant.github.io/backtrader/user_guide/)
- [API Reference](https://cloudquant.github.io/backtrader/api_reference/)
- [Migration Guide](https://cloudquant.github.io/backtrader/migration/1_0_to_1_1)

### Full Changelog

See [CHANGELOG.md](https://github.com/cloudQuant/backtrader/blob/dev/CHANGELOG.md)

### Contributors

@contributor1 @contributor2 @contributor3

Thank you to all contributors!
```

## Post-Release Tasks

### 1. Prepare for Next Release

```bash
# Update CHANGELOG.md for next cycle
vim CHANGELOG.md

# Add new Unreleased section
## [Unreleased] - dev branch

### Added
- (placeholder for next features)

### Changed
- (placeholder for next changes)
```

### 2. Announcements

**Create announcements in:**

1. **GitHub Discussions** - Release announcement
2. **Gitter/Discord** - Community notification
3. **Twitter/X** - Social media post

**Announcement Template:**

```
Backtrader v1.1.0 is now available!

New features:
- CCXT WebSocket support for real-time trading
- Plotly interactive charts
- 45% performance boost

Install: pip install backtrader==1.1.0
Full details: https://github.com/cloudQuant/backtrader/releases/tag/v1.1.0

#python #trading #backtesting
```

### 3. Documentation Updates

- [ ] Update version number in documentation home page
- [ ] Update installation instructions with new version
- [ ] Add migration guide if breaking changes
- [ ] Update examples if API changed

### 4. Cleanup

```bash
# Delete release branch (local and remote)
git branch -d release/1.1.0
git push origin --delete release/1.1.0

# Clean build artifacts
make clean
```

### 5. Monitor Issues

After release, monitor for:
- New issues related to the release
- Regression reports
- Installation problems
- Documentation confusion

## Release Cadence

| Release Type | Frequency | Example |
|--------------|-----------|---------|
| **PATCH** | As needed (bug fixes) | 1.1.0 → 1.1.1 |
| **MINOR** | Every 1-3 months | 1.1.0 → 1.2.0 |
| **MAJOR** | 6-12 months | 1.x.x → 2.0.0 |

### Release Candidates

For major releases, consider releasing RC versions:

```bash
# RC1
git tag -a v2.0.0rc1 -m "Release candidate 1"
git push origin v2.0.0rc1

# After feedback, RC2
git tag -a v2.0.0rc2 -m "Release candidate 2"
git push origin v2.0.0rc2

# Final release
git tag -a v2.0.0 -m "Release v2.0.0"
git push origin v2.0.0
```

## Emergency Releases

For critical security issues or severe bugs:

```bash
# Create hotfix branch from master
git checkout master
git checkout -b hotfix/critical-security-fix

# Apply fix
# ... make changes ...

# Test thoroughly
pytest tests/ -v -m priority_p0

# Merge to master and dev
git checkout master
git merge hotfix/critical-security-fix
git tag -a v1.1.1 -m "Hotfix: Critical security fix"

git checkout dev
git merge hotfix/critical-security-fix

# Push
git push origin master dev --tags
```

## Quick Reference Card

```bash
# Release commands cheat sheet
make clean                              # Clean build artifacts
make test-coverage                      # Verify tests pass
make docs                               # Build documentation
make quality-check                      # Verify code quality

python -m build                         # Build distributions
twine upload dist/*                     # Publish to PyPI

git tag -a vX.Y.Z -m "Release vX.Y.Z"  # Create release tag
git push origin --tags                  # Push tags
```

## Troubleshooting

### Version Mismatch

If installed version doesn't match:

```bash
# Check installed version
pip show backtrader

# Uninstall old version
pip uninstall backtrader

# Install specific version
pip install backtrader==1.1.0
```

### Build Failures

If build fails:

```bash
# Ensure clean state
make clean
git status

# Check for uncommitted changes
git diff

# Rebuild from scratch
rm -rf dist/ build/ *.egg-info/
python -m build
```

### PyPI Upload Errors

Common errors:

1. **Version already exists**: Increment version number
2. **Invalid package name**: Check `setup.py` name field
3. **Long description error**: Ensure README.md exists and is valid markdown

## Additional Resources

- [Semantic Versioning](https://semver.org/)
- [Keep a Changelog](https://keepachangelog.com/)
- [Python Packaging Guide](https://packaging.python.org/)
- [PyPI Publishing](https://pypi.org/help/#apitoken)
