# Development Guide

## Prerequisites

- Python 3.8 or higher (tested up to 3.13)
- pip package manager
- Git

## Environment Setup

### 1. Clone and Install

```bash

# Clone the repository

git clone <https://github.com/cloudQuant/backtrader.git>
cd backtrader

# Switch to dev branch (active development)

git checkout dev

# Install dependencies

pip install -r requirements.txt

# Install in development mode

pip install -e .

```bash

### 2. Optional: Compile Cython Extensions

- *Note**: Cython is being phased out in favor of C++ for future optimizations.

```bash

# Unix/Mac

cd backtrader && python -W ignore compile_cython_numba_files.py && cd ..
pip install -U .

# Windows

cd backtrader; python -W ignore compile_cython_numba_files.py; cd ..
pip install -U .

```bash

### 3. Verify Installation

```bash
python -m pytest tests/new_functions/ -v

```bash

## Development Commands

### Running Tests

```bash

# All tests (parallel execution recommended)

pytest tests/ -n 4 -v

# Original tests only

pytest tests/original_tests/ -v

# With coverage

make test-coverage

# Single test with detailed output

pytest tests/path/to/test_file.py::test_function_name -v --tb=short

# Integration tests (requires testnet keys)

pytest tests/ -m "integration" -v

# Exclude integration tests (fast)

pytest tests/ -m "not integration" -v

```bash

### Code Quality

```bash

# Format code with Black

make format

# Check formatting

make format-check

# Run linter (Pylint)

make lint

# Type checking

make type-check

# Security checks

make security

# All quality checks

make quality-check

# Full code optimization script

bash scripts/optimize_code.sh

```bash

### Documentation

```bash

# Generate all documentation (en + zh)

make docs

# Generate English documentation

make docs-en

# Generate Chinese documentation

make docs-zh

# Build with live reload (development)

make docs-live

# View in browser

make docs-view

# See all commands

make help

```bash

## Code Style

### Formatting

- **Tool**: Black
- **Line Length**: 124 characters
- **Target Versions**: Python 3.8-3.13

### Import Order

1. Standard library
2. Third-party
3. Local modules

Use `isort` for automatic import sorting.

### Type Hints

- Encouraged but not mandatory
- Core APIs (Cerebro) have type annotations

### Comments

- **Code comments in ENGLISH**
- **Google-style docstrings**

## Testing Guidelines

### Test Organization

```bash
tests/
├── original_tests/     # Core functionality (300+ tests)

├── add_tests/          # Additional test coverage

├── refactor_tests/     # Metaclass removal tests

└── strategies/         # Strategy-specific tests

```bash

### Test Naming

- Files: `test_<module>.py`
- Functions: `test_<feature>_<scenario>()`
- Test IDs: `EPIC.STORY-LEVEL-SEQ` format

### Priority Markers

- `priority_p0`: Core functionality (Critical)
- `priority_p1`: Core user journeys (High)
- `priority_p2`: Secondary features (Medium)
- `priority_p3`: Rarely used features (Low)
- `integration`: Requires live connection
- `websocket`: WebSocket-specific
- `trading`: Sandbox order tests

## Common Development Tasks

### Adding a New Indicator

1. Create file in `backtrader/indicators/`
2. Inherit from `bt.Indicator`
3. Define `lines` for result storage
4. Define `params` with defaults
5. Implement `__init__()` with calculation logic
6. Add to `indicators/__init__.py`

### Adding a New Strategy

1. Inherit from `bt.Strategy`
2. Define parameters with `params = (...)`
3. Implement `__init__()` to set up indicators
4. Implement `next()` for trading logic
5. Use `self.buy()`, `self.sell()`, `self.close()` for orders

## Debugging Tips

### Check Indicator Registration

```python
def __init__(self):
    super().__init__()
    self.sma = bt.indicators.SMA(period=20)

# Verify registration
    assert self.sma in self._lineiterators[0]

```bash

### Debug Line Issues

- Check `len(obj)` returns expected value
- Verify `obj._minperiod` is set correctly
- Ensure `obj._owner` is assigned
- For indicators, verify `obj._ltype == 0` (IndType)

## Git Workflow

### Branch Strategy

| Branch | Purpose |

|--------|---------|

| `dev` | Active development (45% performance, tick-level tests, C++ integration) |

| `master` | Stable version (aligned with official backtrader) |

| `development` | Main branch (PR target) |

### Commit Format

```bash
<type>: <description>

[optional body]

```bash
Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`

### Release Process

1. Update CHANGELOG.md
2. Create version tag (e.g., `v1.1.0`)
3. Merge to `master` branch
