# Tech Stack & Build System

## Language & Runtime

- Python 3.8+ (tested on 3.8–3.13, 3.11 recommended for performance)
- Cython extensions for performance-critical calculations

## Core Dependencies

- numpy, pandas, scipy, statsmodels — numerical computation
- matplotlib — default plotting backend
- plotly, bokeh, dash, pyecharts — optional visualization backends
- pytz, python-dateutil — timezone and date handling

## Dev Dependencies

- pytest, pytest-xdist, pytest-benchmark, pytest-cov, pytest-html, pytest-timeout, pytest-asyncio
- ruff — linting (select E, F; line-length 121)
- black — formatting (line-length 100)
- isort — import sorting (profile: black)
- mypy — type checking
- bandit — security scanning
- pre-commit — git hooks (pyupgrade, ruff, trailing whitespace, etc.)

## Build & Install

```bash
# Install from source (not on PyPI)
pip install -r requirements.txt
pip install -U .

# Dev install (editable)
pip install -e .

# Compile Cython extensions
cd backtrader && python -W ignore compile_cython_numba_files.py && cd .. && pip install -U .
```

## Common Commands

```bash
# Run all tests (parallel recommended)
pytest tests/ -n 4 -v

# Run tests with coverage
make test-coverage

# Format code
make format            # black, line-length 100
black --check ...      # check only

# Lint
ruff check backtrader  # fast linter

# Type check
make type-check        # mypy

# Full quality pipeline
bash scripts/optimize_code.sh   # pyupgrade + isort + black + ruff + tests

# All quality checks (no tests)
make quality-check

# Generate documentation
make docs              # both EN and ZH
make docs-en           # English only
make docs-zh           # Chinese only

# Clean artifacts
make clean

# See all make targets
make help
```

## Code Style Rules

- Line length: 100 (Black), 121 (ruff/isort)
- Python 3.11+ syntax via pyupgrade in pre-commit
- Type hints encouraged but not strictly required
- Docstrings on all public methods
- Comments in both English and Chinese are acceptable
- Never introduce new metaclasses — use mixins with `donew()` pattern
- Minimize `isinstance()`, `hasattr()`, `len()` in hot paths
