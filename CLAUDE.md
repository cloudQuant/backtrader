# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a modified version of the backtrader Python library for quantitative trading and backtesting. It's an enhanced fork that adds performance optimizations using Cython/C++ extensions, support for cryptocurrency trading, and vectorized backtesting frameworks (cs.py and ts.py).

## Development Commands

### Installation and Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Compile Cython extensions (required for performance optimizations)
# Windows:
cd backtrader && python -W ignore compile_cython_numba_files.py && cd .. && pip install -U .

# Mac/Linux:
cd backtrader && python -W ignore compile_cython_numba_files.py && cd .. && pip install -U .
```

### Testing
```bash
# Run all tests with parallel execution
pytest tests -n 4

# Run specific test directories
pytest tests/original_tests
pytest tests/base_functions
pytest tests/funding_rate_examples
```

### Building
```bash
# Install in development mode
pip install -e .

# Build distribution packages
python setup.py sdist bdist_wheel
```

## Architecture

### Core Components

- **Cerebro** (`cerebro.py`): Main engine that orchestrates data feeds, strategies, brokers, and observers
- **Strategy** (`strategy.py`): Base class for trading strategies with event-driven execution
- **Data Feeds** (`feeds/`): Market data providers including CSV, cryptocurrency exchanges (CCXT), Interactive Brokers, CTP
- **Brokers** (`brokers/`): Execution engines supporting various brokers (IB, crypto exchanges, CTP)
- **Indicators** (`indicators/`): Technical analysis indicators with vectorized computation
- **Analyzers** (`analyzers/`): Performance metrics and statistics calculators

### Enhanced Features

- **Vectorized Backtesting**: 
  - `vectors/cs.py`: Cross-sectional (multi-asset) vectorized backtesting
  - `vectors/ts.py`: Time-series vectorized backtesting for single assets
- **Performance Optimizations**: Cython extensions in `utils/` for critical calculations
- **Cryptocurrency Support**: CCXT integration for crypto exchanges with funding rate calculations
- **CTP Integration**: Support for China's CTP (Comprehensive Transaction Platform)

### Key Directories

- `backtrader/`: Main library code
- `strategies/`: Example trading strategies
- `tests/`: Comprehensive test suite
- `utils/`: Performance-critical utilities with Cython implementations
- `feeds/`: Data feed implementations for various sources
- `brokers/`: Broker integration modules
- `indicators/`: Technical indicators library

## Important Notes

- The codebase uses both Python and Cython for performance optimization
- Cython compilation is required for full functionality
- The library supports both traditional event-driven and vectorized backtesting approaches
- Extensive support for cryptocurrency trading including funding rate calculations
- Multi-platform support (Windows, macOS, Linux) with platform-specific optimizations

## Testing Framework

Uses pytest with multiple test categories:
- `original_tests/`: Core library functionality tests
- `base_functions/`: Basic utility function tests  
- `funding_rate_examples/`: Cryptocurrency-specific functionality
- Performance tests using pytest-benchmark for optimization validation