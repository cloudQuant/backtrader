# Project Structure

## Repository Classification

- **Type**: Monolith (Single cohesive codebase)
- **Primary Language**: Python
- **Project Type**: Library (quantitative trading framework)

## Project Parts

| Part ID | Type | Root Path | Description |

|---------|------|-----------|-------------|

| main | library | /Users/yunjinqi/Documents/量化交易框架/backtrader | Core backtrader framework |

## Key Technologies

- Python 3.8+
- pandas (data processing)
- numpy (numerical computing)
- matplotlib, plotly, pyecharts (visualization)
- pytest (testing)
- CCXT (crypto exchange API)
- ctp-python (futures trading)

## Directory Structure

```bash
backtrader/
├── backtrader/           # Main package (core library)

│   ├── indicators/       # Technical indicators (60+ indicators)

│   ├── observers/        # Chart observers

│   ├── analyzers/        # Performance analyzers

│   ├── feeds/           # Data sources (CSV, pandas, live)

│   ├── brokers/         # Broker implementations

│   ├── stores/          # Data storage layer

│   ├── signals/         # Signal system

│   ├── utils/           # Utility functions

│   ├── plot/            # Plotting (matplotlib, plotly)

│   ├── ccxt/            # CCXT enhancement module

│   └── ...
├── tests/               # Test suite

│   ├── original_tests/  # Core functionality tests

│   ├── add_tests/       # Additional tests

│   └── refactor_tests/  # Metaclass removal tests

├── docs/                # Documentation

├── _bmad/               # BMAD workflow configuration

└── tools/               # Utility scripts

```bash

## Critical Directories

- **backtrader/**- Core library code
- **backtrader/indicators/**- 60+ technical indicators
- **backtrader/observers/**- Chart observers and data recorders
- **backtrader/analyzers/**- Performance metrics and statistics
- **backtrader/feeds/**- Data source adapters
- **backtrader/brokers/**- Order execution and portfolio management
- **backtrader/stores/**- Connection and data storage management
- **tests/** - Comprehensive test suite
