# Release Process

## Version Scheme

`MAJOR.MINOR.PATCH` (e.g., `1.1.0`)

- **MAJOR**: Breaking API changes
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes only

## Release Checklist

### 1. Pre-release Verification

```bash

# Run full test suite

python -m pytest tests/ --timeout=120 -q

# Run integration tests (requires .env credentials)

python -m pytest tests/integration/ -m integration -v --timeout=60

# Check test coverage

python -m pytest tests/ --cov=backtrader --cov-report=term-missing:skip-covered -q

```bash

### 2. Update Version

Edit `backtrader/version.py`:

```python
__version__ = "X.Y.Z"

```bash

### 3. Update CHANGELOG

In `CHANGELOG.md`:

1. Move items from `[Unreleased]` to a new version section
2. Add the release date
3. Categorize changes: Added / Changed / Fixed / Removed

### 4. Commit and Tag

```bash
git add backtrader/version.py CHANGELOG.md
git commit -m "release: vX.Y.Z — brief description"
git tag -a vX.Y.Z -m "vX.Y.Z: brief description"

```bash

### 5. Push

```bash
git push origin dev
git push origin vX.Y.Z

```bash

### 6. Post-release

- Create GitHub Release from tag (optional)
- Update `[Unreleased]` section in CHANGELOG for next cycle

## Branch Strategy

| Branch | Purpose | Merge Target |

|--------|---------|-------------|

| `dev` | Active development | — |

| `master` | Stable releases | Tagged from `dev` |

| `crypto` | Archived (fully merged into dev) | — |

| `ctp` | CTP futures feature branch | `dev` when ready |

| `dev_cython` | Cython acceleration experiments | `dev` when stable |

## Previous Releases

| Version | Date | Highlights |

|---------|------|-----------|

| v1.1.0 | 2026-02-24 | P2 WebSocket live trading features |

| v1.0.0 | 2025 | Metaclass removal, 45% performance boost |
