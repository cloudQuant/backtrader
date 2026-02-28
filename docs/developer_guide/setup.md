---
title: Development Setup
description: Setting up development environment
---

# Development Setup

This guide covers setting up a Backtrader development environment.

## Prerequisites

- Python 3.8 or higher
- Git
- pip

## Clone Repository

```bash
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader
```

## Install Development Dependencies

```bash
# Install dependencies
pip install -r requirements.txt

# Install in development mode
pip install -e .
```

## Development Commands

### Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/strategies/test_signals.py -v

# Run with parallel execution
pytest tests/ -n 4 -v

# With coverage
pytest tests/ -m "not integration" --cov=backtrader
```

### Code Quality

```bash
# Format code
bash scripts/optimize_code.sh

# Or individual steps
pyupgrade --py38-plus backtrader/
isort backtrader/
black --line-length 124 backtrader/
ruff check --fix backtrader/
```

### Type Checking

```bash
# Run mypy
mypy backtrader/

# Or use make target
make type-check
```

### Documentation

```bash
# Generate documentation
make docs

# View documentation
make docs-view
```

## Project Structure

```
backtrader/
├── backtrader/           # Main package
│   ├── core/            # Core classes
│   ├── indicators/      # Technical indicators
│   ├── observers/       # Observers
│   ├── analyzers/       # Performance analyzers
│   ├── feeds/           # Data feeds
│   ├── brokers/         # Broker implementations
│   ├── stores/          # Data stores
│   └── utils/           # Utilities
├── tests/                # Test suite
│   ├── original_tests/
│   ├── add_tests/
│   └── strategies/
├── docs/                 # Documentation
├── scripts/              # Utility scripts
└── tools/                # Development tools
```

## Git Workflow

### Branches

- `dev` - Active development
- `master` - Stable releases
- `development` - Main branch

### Commit Format

Follow conventional commits:

```
<type>: <description>

[optional body]
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`

### Creating Pull Requests

1. Fork and branch from `dev`
2. Make your changes
3. Ensure tests pass
4. Submit PR to `dev` branch

## Testing Your Changes

### Unit Tests

```python
# tests/test_my_feature.py
import backtrader as bt
import pytest

def test_my_feature():
    cerebro = bt.Cerebro()
    # ... setup
    result = cerebro.run()
    assert result is not None
```

### Integration Tests

```python
@pytest.mark.integration
def test_live_connection():
    # Requires testnet credentials
    pass
```

### Running Specific Tests

```bash
# Indicator tests
pytest tests/indicators/test_sma.py

# Strategy tests
pytest tests/strategies/test_signals.py

# With markers
pytest tests/ -m "priority_p0"  # Critical tests only
pytest tests/ -m "not integration"  # Skip integration tests
```

## Code Style Guidelines

### Formatting

- **Line length**: 124 characters
- **Formatter**: Black
- **Import order**: isort (Black profile)

### Type Hints

```python
def calculate_sma(period: int, data: list) -> float:
    """Calculate Simple Moving Average.

    Args:
        period: Number of periods.
        data: Input data series.

    Returns:
        Calculated SMA value.
    """
    pass
```

### Comments

- Use English for code comments
- Google-style docstrings
- Explain "why", not "what"

## Development Tips

### Using pdb

```python
import pdb

def next(self):
    pdb.set_trace()
    # Your code here
```

### Logging

```python
from backtrader.utils import SpdLogManager

logger = SpdLogManager().get_logger(__name__)
logger.info('Strategy initialized')
```

### Quick Testing

```python
# Quick test script
if __name__ == '__main__':
    cerebro = bt.Cerebro()
    # ... setup
    cerebro.run()
    cerebro.plot()
```

## See Also

- [Testing](testing.md)
- [Code Style](style.md)
- [Contributing](contributing.md)
