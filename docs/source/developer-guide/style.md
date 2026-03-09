- --

title: Code Style Guide
description: Python code formatting and style conventions for Backtrader

- --

# Code Style Guide

This guide covers the code formatting and style conventions used in the Backtrader project. Following these guidelines ensures consistent, readable, and maintainable code.

## Table of Contents

- [Formatting Rules](#formatting-rules)
- [Import Order Conventions](#import-order-conventions)
- [Type Hint Guidelines](#type-hint-guidelines)
- [Docstring Conventions](#docstring-conventions)
- [Comment Standards](#comment-standards)
- [Naming Conventions](#naming-conventions)
- [Code Quality Tools](#code-quality-tools)
- [Pre-commit Hooks](#pre-commit-hooks)

## Formatting Rules

### Line Length

- **Maximum line length**: 124 characters
- **Soft limit**: 100 characters (preferred for readability)
- **Reasoning**: Balance between readability and practical data structure definitions

### Indentation

- **Spaces**: 4 spaces (Python standard)
- **Tabs**: Never use tabs

### Trailing Whitespace

- No trailing whitespace allowed
- Enforced by pre-commit hooks

### Line Endings

- **Unix-style (LF)**: Required
- **Windows-style (CRLF)**: Automatically converted to LF

### Blank Lines

- **Top-level**: 2 blank lines between class/function definitions
- **Inside class**: 1 blank line between method definitions
- **Inside function**: Use blank lines sparingly to separate logical sections

### Example

```python

# Good: Proper spacing and line length

class MyIndicator(bt.Indicator):
    """A custom indicator for demonstration."""

    lines = ('signal',)
    params = (
        ('period', 14),
        ('threshold', 0.5),
    )

    def __init__(self):

# Calculate the indicator value
        self.lines.signal = bt.indicators.RSI(self.data, period=self.p.period)

```bash

## Import Order Conventions

### Standard Order (isort with Black profile)

1. Standard library imports
2. Third-party imports
3. Local application imports
4. Relative imports (from current package)

### Formatting Rules

- **Grouping**: Separate groups with blank line
- **Sorting**: Alphabetical within each group
- **Line length**: Use `ruff format` for automatic wrapping

### Example

```python

# Standard library

import datetime
from pathlib import Path

# Third-party

import numpy as np
import pandas as pd

# Local application

from backtrader.indicators import Indicator
from backtrader.lineseries import LineSeries

# Relative (from current package)

from .utils import calculate_value

```bash

### Import Aliases

Follow these conventions for common libraries:

```python
import backtrader as bt
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

```bash

### Wildcard Imports

- *Avoid wildcard imports** except for specific cases:

```python

# Allowed in __init__.py for exposing public API

from .indicator import *
from .observers import *

# Never in regular modules

# from indicators import *# BAD

```bash

## Type Hint Guidelines

### When to Use Type Hints

- *Required for**:
- Public API methods
- Complex function signatures
- Functions returning non-obvious types
- Class method parameters

- *Optional for**:
- Private methods (prefixed with `_`)
- Simple, obvious cases
- Performance-critical code (type hints have overhead)

### Basic Syntax

```python
def calculate_sma(period: int, data: list[float]) -> float:
    """Calculate Simple Moving Average."""
    return sum(data[:period]) / period

```bash

### Common Types

```python
from typing import Optional, List, Dict, Union, Callable

def process_data(
    data: pd.DataFrame,
    period: int = 14,
    callback: Optional[Callable[[float], None]] = None,
) -> Dict[str, float]:
    """Process data with optional callback."""
    pass

```bash

### Type Hints for Backtrader

```python
from backtrader import LineLike, StrategyBase

def register_indicator(
    owner: LineIterator,
    indicator: Indicator,
) -> None:
    """Register an indicator with its owner."""
    pass

```bash

### Type Checking

Run mypy to verify type hints:

```bash
mypy backtrader/

```bash

## Docstring Conventions

### Style: Google-style

Use Google-style docstrings for all public classes, methods, and functions.

### Function/Method Docstrings

```python
def calculate_rsi(prices: list[float], period: int = 14) -> list[float]:
    """Calculate Relative Strength Index.

    The RSI is a momentum indicator that measures the magnitude of recent
    price changes to evaluate overbought or oversold conditions.

    Args:
        prices: List of price values.
        period: Number of periods for calculation. Defaults to 14.

    Returns:
        List of RSI values. Same length as input prices.

    Raises:
        ValueError: If period is less than 2 or prices list is empty.

    Example:
        >>> calculate_rsi([100, 102, 98, 105], period=3)
        [None, None, 50.0, 75.0]
    """
    if period < 2:
        raise ValueError(f"Period must be at least 2, got {period}")

# Implementation...

```bash

### Class Docstrings

```python
class CustomIndicator(bt.Indicator):
    """A custom technical indicator for trend analysis.

    This indicator combines multiple moving averages to identify
    trend direction and strength.

    Attributes:
        lines: Contains 'trend' line for output.
        params: Configuration parameters.

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(MyStrategy)
        >>> cerebro.run()
    """

```bash

### Module Docstrings

```python
"""Custom indicators module.

This module contains custom technical indicators that extend
the standard Backtrader indicator library.

Typical usage:
    from backtrader.indicators.custom import CustomIndicator
    cerebro.addindicator(CustomIndicator)
"""

```bash

## Comment Standards

### Language: English Only

- *All code comments must be in English**. This ensures consistency across the international codebase.

```python

# Good

# Calculate the signal based on price momentum

signal = self.data.close[0] - self.data.close[-1]

# Bad

# 根据价格动量计算信号

signal = self.data.close[0] - self.data.close[-1]

```bash

### When to Comment

- *DO comment**:
- Complex algorithms
- Non-obvious business logic
- Workarounds for bugs/issues
- Performance-critical sections
- Public API documentation

- *DON'T comment**:
- Obvious code (self-documenting)
- Outdated information
- Copy-pasted code without adjustment

### Comment Style

```python

# Single-line comments explain why, not what

# BAD:

# Increment counter

counter += 1

# GOOD:

# Reset counter after reaching threshold to prevent overflow

counter = 0 if counter >= MAX_THRESHOLD else counter + 1

```bash

### TODO/FIXME Comments

```python

# TODO: Add support for multiple timeframes

# FIXME: This fails when data contains NaN values

# HACK: Temporary workaround for upstream bug in numpy 1.x

# NOTE: Performance optimization opportunity in hot path

```bash

### Block Comments

```python

# The following calculation implements the EMA formula:

# EMA(today) = Value(today) *k + EMA(yesterday)*(1 - k)

# where k = 2 / (period + 1)
#

# This implementation matches the behavior of pandas.ewm()

k = 2 / (period + 1)
ema_today = current_value*k + ema_yesterday*(1 - k)

```bash

## Naming Conventions

### General Rules

Follow PEP 8 naming conventions:

| Type | Convention | Example |

|------|------------|---------|

| Module | `lowercase_with_underscores` | `linebuffer.py` |

| Class | `CapitalizedWords` | `LineIterator` |

| Function | `lowercase_with_underscores` | `calculate_sma()` |

| Method | `lowercase_with_underscores` | `get_value()` |

| Constant | `UPPERCASE_WITH_UNDERSCORES` | `MAX_PERIOD` |

| Variable | `lowercase_with_underscores` | `close_price` |

| Private | `_leading_underscore` | `_internal_method()` |

| Protected | `__double_underscore` | `__private_attr` |

### Backtrader-specific Names

```python

# Lines (output series)

class MyIndicator(bt.Indicator):
    lines = ('signal', 'trend')  # lowercase, tuple

# Parameters

params = (
    ('period', 14),           # lowercase
    ('use_threshold', True),
)

# Accessing

self.p.period      # Parameter access

self.lines.signal  # Line access

```bash

### Booleans

Use `is_` or `has_` prefix for boolean variables:

```python
is_valid = True
has_data = False
should_recalculate = True

```bash

### Avoid Single-letter Names

Except for loop variables and mathematical notation:

```python

# Good

for index in range(len(data)):
    price = data[index]

# Acceptable

for i, price in enumerate(data):
    pass

# Bad (unclear meaning)

x = calculate()
y = process(x)

```bash

## Code Quality Tools

### pyupgrade

Automatically upgrade Python syntax to newer versions:

```bash

# Upgrade to Python 3.8+ syntax

pyupgrade --py38-plus backtrader/

# Upgrade to Python 3.11+ syntax

pyupgrade --py311-plus backtrader/

```bash

- *What it does**:
- Converts `%` formatting to f-strings
- Replaces `super()` calls
- Modernizes type hints
- Removes unnecessary `object` inheritance

### ruff

Fast Python linter and formatter:

```bash

# Check for issues

ruff check backtrader/

# Auto-fix issues

ruff check --fix backtrader/

# Format code

ruff format backtrader/

```bash

- *Configuration** (pyproject.toml):

```toml
[tool.ruff]
line-length = 121
target-version = "py38"

[tool.ruff.lint]
select = ["E", "F"]
ignore = ["E501"]  # Line length handled by formatter

```bash

### isort

Import statement organizer:

```bash

# Sort imports

isort backtrader/

# Check without modifying

isort --check-only backtrader/

```bash

- *Configuration** (pyproject.toml):

```toml
[tool.isort]
profile = "black"
line_length = 121

```bash

### mypy

Static type checker:

```bash

# Run type checking

mypy backtrader/

# Check specific file

mypy backtrader/indicators/sma.py

```bash

- *Configuration**(pyproject.toml):

```toml
[tool.mypy]
python_version = "3.8"
warn_return_any = true
warn_unused_configs = true
check_untyped_defs = true
ignore_missing_imports = true

```bash

### black

Code formatter (note: project uses ruff-format for consistency):

```bash

# Format with Black (if needed)

black --line-length 124 backtrader/

```bash

## Pre-commit Hooks

### Installation

```bash

# Install pre-commit framework

pip install pre-commit

# Install hooks in your repository

pre-commit install

# Run manually on all files

pre-commit run --all-files

```bash

### Hook Configuration

The project uses `.pre-commit-config.yaml` with the following hooks:

1.**pyupgrade**: Auto-upgrade Python syntax

1. **ruff**: Linting and formatting
2. **trailing-whitespace**: Remove trailing spaces
3. **end-of-file-fixer**: Ensure newline at EOF
4. **check-yaml/check-json**: Validate YAML and JSON files
5. **debug-statements**: Prevent debugger commits

### Using Pre-commit

```bash

# Automatic: Runs on every git commit

git commit -m "feat: Add new indicator"

# Manual: Run on all files

pre-commit run --all-files

# Run on specific files

pre-commit run --files backtrader/indicators/*.py

# Skip hooks (not recommended)

git commit --no-verify -m "WIP"

```bash

### Git Setup (Makefile)

```bash

# Setup git hooks automatically

make git-setup

# This creates a pre-commit hook that runs:

make pre-commit

```bash

### Pre-commit Output

```bash
$ git commit -m "Add new feature"

Trim trailing whitespace.................................................Passed
Fix end of files.........................................................Passed
Check Yaml..............................................................Passed
pyupgrade...............................................................Passed
ruff-format............................................................Passed
ruff-lint................................................................Passed
[dev abc1234] Add new feature
 1 file changed, 42 insertions(+)

```bash

## Quick Reference

### Before Committing

```bash

# Format and check your code

bash scripts/optimize_code.sh

# Or manually

pyupgrade --py38-plus backtrader/
isort backtrader/
ruff format backtrader/
ruff check --fix backtrader/

# Run tests

pytest tests/ -n 4 -v

```bash

### IDE Configuration

- *VS Code** (.vscode/settings.json):

```json
{
  "python.formatting.provider": "none",
  "editor.formatOnSave": true,
  "[python]": {
    "editor.defaultFormatter": "charliemarsh.ruff"
  },
  "ruff.lineLength": 124,
  "ruff.organizeImports": true
}

```bash

- *PyCharm**:
- Enable "Ruff" plugin
- Set line length to 124
- Enable "Optimize imports on save"

## See Also

- [Development Setup](setup.md)
- [Testing Guide](testing.md)
- [Contributing Guidelines](contributing.md)
- [Architecture Overview](../architecture/overview.md)
