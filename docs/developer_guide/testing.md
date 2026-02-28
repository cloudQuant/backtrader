---
title: Testing Guide
description: Testing practices and guidelines for Backtrader developers
---

# Testing Guide

This guide covers testing practices and guidelines for contributing to the Backtrader framework.

## Table of Contents

- [Test Framework](#test-framework)
- [Test Organization](#test-organization)
- [Test Categories](#test-categories)
- [Test Markers](#test-markers)
- [Writing Tests](#writing-tests)
- [Fixtures and Helpers](#fixtures-and-helpers)
- [Coverage Requirements](#coverage-requirements)
- [Running Tests](#running-tests)

## Test Framework

Backtrader uses **pytest** as its testing framework. Key features:

- **pytest**: Test runner and assertion library
- **pytest-cov**: Coverage reporting
- **pytest-xdist**: Parallel test execution

### Installation

```bash
pip install pytest pytest-cov pytest-xdist
```

### Configuration

Test configuration is defined in `pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*

markers =
    priority_p0: Critical tests - core functionality
    priority_p1: High priority tests - core user journeys
    priority_p2: Medium priority tests - secondary features
    priority_p3: Low priority tests - rarely used features
    integration: Integration tests requiring live exchange connectivity
    websocket: WebSocket-specific integration tests
    trading: Tests that place real orders on sandbox exchange

filterwarnings =
    ignore::RuntimeWarning
    ignore::DeprecationWarning
```

## Test Organization

### Directory Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── datas/                   # Test data files
├── original_tests/          # Core functionality tests
├── add_tests/               # Additional test coverage
├── strategies/              # Strategy-specific tests
├── base_functions/          # Base function tests
└── integration/             # Integration tests
```

### Test File Naming

- Test files must start with `test_`: `test_indicator.py`, `test_strategy.py`
- Test classes must start with `Test`: `TestSMA`, `TestBroker`
- Test functions must start with `test_`: `test_sma_calculation()`

## Test Categories

### Unit Tests

Unit tests test individual components in isolation. They should:

- Use mock data (no external dependencies)
- Execute quickly (< 1 second per test)
- Test a single behavior per test

```python
def test_sma_calculation():
    """Test SMA indicator calculates correctly."""
    # Create test data
    data = [1, 2, 3, 4, 5]
    period = 3

    # Expected result
    expected = 3.0  # (3 + 4 + 5) / 3

    # Run test
    result = calculate_sma(data, period)

    # Assert
    assert result == expected
```

### Integration Tests

Integration tests verify that multiple components work together. They:

- Use real data feeds or testnet connections
- Are marked with `@pytest.mark.integration`
- May require API keys or external services

```python
import backtrader as bt
import pytest

@pytest.mark.integration
def test_ib_connection():
    """Test Interactive Brokers connection (requires testnet)."""
    cerebro = bt.Cerebro()
    store = bt.stores.IBStore(port=7497)  # paper trading port
    data = store.getdata(dataname='AAPL')

    cerebro.adddata(data)
    result = cerebro.run()
    assert len(result) > 0
```

### Priority Levels

Tests are categorized by priority:

| Priority | Description | When to Use |
|----------|-------------|-------------|
| `priority_p0` | Critical - core functionality | Essential features, data loading, order execution |
| `priority_p1` | High - frequently used | Common indicators, standard strategies |
| `priority_p2` | Medium - secondary features | Less common indicators, edge cases |
| `priority_p3` | Low - rarely used | Obscure features, legacy code |

## Test Markers

### Using Markers

```python
import pytest

@pytest.mark.priority_p0
def test_data_feed_loading():
    """Critical test - data feeds must load correctly."""
    pass

@pytest.mark.priority_p1
@pytest.mark.integration
def test_live_api_connection():
    """High priority integration test."""
    pass

@pytest.mark.websocket
async def test_websocket_feed():
    """WebSocket-specific test."""
    pass
```

### Running with Markers

```bash
# Run only critical tests
pytest tests/ -m "priority_p0"

# Skip integration tests
pytest tests/ -m "not integration"

# Run multiple markers
pytest tests/ -m "priority_p0 or priority_p1"

# Skip WebSocket tests
pytest tests/ -m "not websocket"
```

## Writing Tests

### Test Structure

A good test follows the Arrange-Act-Assert pattern:

```python
def test_indicator_calculation():
    """Test indicator calculates expected values."""
    # Arrange - Set up test data and conditions
    cerebro = bt.Cerebro()
    data = create_test_data()
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)

    # Act - Execute the code being tested
    result = cerebro.run()

    # Assert - Verify expected outcomes
    assert len(result) == 1
    assert result[0].analyzers.sharpe.get_analysis()['sharperatio'] > 0
```

### Complete Test Example

Here's a complete example for testing an indicator:

```python
#!/usr/bin/env python
"""Test Simple Moving Average indicator."""

import backtrader as bt
import pytest
import datetime

class TestStrategy(bt.Strategy):
    """Test strategy for SMA validation."""

    params = (
        ('period', 15),
    )

    def __init__(self):
        """Initialize indicator and test parameters."""
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.expected_values = []
        self.actual_values = []

    def next(self):
        """Record SMA values for validation."""
        if len(self.data) > self.p.period:
            self.actual_values.append(self.sma[0])

    def stop(self):
        """Validate SMA calculations."""
        assert len(self.actual_values) > 0, "No SMA values calculated"
        # Additional assertions here


@pytest.mark.priority_p0
def test_sma_basic_calculation():
    """Test SMA calculates correctly with basic data."""
    cerebro = bt.Cerebro()

    # Create simple test data
    data = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-001.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 1, 31),  # One month
    )

    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy, period=15)
    cerebro.broker.setcash(10000.0)

    results = cerebro.run()

    # Verify strategy ran
    assert len(results) == 1
    strat = results[0]

    # Verify SMA was calculated
    assert hasattr(strat, 'sma')
    assert len(strat.sma) > 0


@pytest.mark.priority_p1
@pytest.mark.parametrize("period", [5, 10, 15, 20, 30])
def test_sma_different_periods(period):
    """Test SMA with different period values."""
    cerebro = bt.Cerebro()

    data = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-001.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 2, 28),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy, period=period)

    results = cerebro.run()
    assert len(results) == 1


@pytest.mark.priority_p2
def test_sma_with_multiple_data_feeds():
    """Test SMA with multiple data feeds."""
    cerebro = bt.Cerebro()

    data1 = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-001.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 3, 31),
    )

    data2 = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-002.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 3, 31),
    )

    cerebro.adddata(data1)
    cerebro.adddata(data2)
    cerebro.addstrategy(TestStrategy, period=10)

    results = cerebro.run()
    assert len(results) == 1
```

### Testing Strategies

When testing trading strategies, focus on:

1. **Order execution**: Verify orders are placed correctly
2. **Position management**: Check positions open/close as expected
3. **Indicator usage**: Ensure indicators are properly initialized

```python
def test_strategy_buy_signal():
    """Test strategy executes buy on signal."""
    cerebro = bt.Cerebro()

    class BuyTestStrategy(bt.Strategy):
        def __init__(self):
            self.buy_executed = False
            self.sma_fast = bt.indicators.SMA(period=5)
            self.sma_slow = bt.indicators.SMA(period=15)

        def next(self):
            if not self.buy_executed:
                if self.sma_fast[0] > self.sma_slow[0]:
                    self.buy()
                    self.buy_executed = True

    data = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-001.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 6, 30),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(BuyTestStrategy)

    results = cerebro.run()
    strat = results[0]

    # Verify at least one buy order was executed
    assert strat.buy_executed
```

### Testing with Mock Data

For isolated unit tests, create mock data:

```python
import backtrader as bt

class MockData(bt.feeds.PandasData):
    """Mock data feed for testing."""
    params = (
        ('datetime', None),
        ('open', -1),
        ('high', -1),
        ('low', -1),
        ('close', -1),
        ('volume', -1),
        ('openinterest', -1),
    )

def create_mock_data():
    """Create a simple mock data feed."""
    import pandas as pd

    dates = pd.date_range('2023-01-01', periods=100, freq='D')
    data = pd.DataFrame({
        'datetime': dates,
        'open': 100 + range(100),
        'high': 102 + range(100),
        'low': 99 + range(100),
        'close': 101 + range(100),
        'volume': 1000,
    })

    return MockData(dataname=data)

def test_with_mock_data():
    """Test indicator with mock data."""
    cerebro = bt.Cerebro()
    data = create_mock_data()
    cerebro.adddata(data)
    cerebro.addstrategy(bt.Strategy)

    result = cerebro.run()
    assert len(result) > 0
```

## Fixtures and Helpers

### Built-in Fixtures

The `conftest.py` file provides shared fixtures:

```python
@pytest.fixture
def sample_data(datas_path):
    """Provide standard sample data feed for testing."""
    datapath = datas_path / "2006-day-001.txt"
    data = bt.feeds.BacktraderCSVData(
        dataname=str(datapath),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )
    return data

@pytest.fixture
def cerebro_engine():
    """Provide basic Cerebro engine instance."""
    cerebro = bt.Cerebro()
    yield cerebro
    # Cleanup
    cerebro = None

@pytest.fixture
def cerebro_with_cash(cerebro_engine):
    """Provide Cerebro with initial cash set."""
    cerebro_engine.broker.setcash(10000.0)
    return cerebro_engine
```

### Using Fixtures

```python
def test_with_fixture(sample_data, cerebro_engine):
    """Test using fixtures from conftest.py."""
    cerebro_engine.adddata(sample_data)
    cerebro_engine.addstrategy(bt.Strategy)

    result = cerebro_engine.run()
    assert len(result) > 0
```

### Creating Custom Fixtures

```python
# In your test file or conftest.py
@pytest.fixture
def macd_indicator():
    """Create MACD indicator with standard parameters."""
    class MACDStrategy(bt.Strategy):
        def __init__(self):
            self.macd = bt.indicators.MACD(period_me1=12,
                                           period_me2=26,
                                           period_signal=9)

    return MACDStrategy
```

## Coverage Requirements

### Coverage Configuration

Coverage is configured in `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["backtrader"]
omit = [
    "*/tests/*",
    "*/test_*",
    "setup.py",
    "*/crypto_tests/*"
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if self.debug:",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
]
```

### Running Coverage

```bash
# Generate coverage report
pytest tests/ --cov=backtrader --cov-report=term-missing

# Generate HTML report
pytest tests/ --cov=backtrader --cov-report=html

# Combine with markers
pytest tests/ -m "not integration" --cov=backtrader
```

### Coverage Goals

- **New code**: Aim for 90%+ coverage
- **Critical paths**: 100% coverage (P0 tests)
- **Existing code**: Maintain current coverage levels

## Running Tests

### Basic Commands

```bash
# Run all tests
pytest tests/ -v

# Run with parallel execution (4 workers)
pytest tests/ -n 4 -v

# Run specific test file
pytest tests/add_tests/test_sma.py -v

# Run specific test function
pytest tests/add_tests/test_sma.py::test_sma_calculation -v

# Stop on first failure
pytest tests/ -x

# Show local variables on failure
pytest tests/ -l

# Verbose output with print statements
pytest tests/ -s
```

### Running by Category

```bash
# Indicator tests
pytest tests/add_tests/test_ind*.py tests/original_tests/test_ind*.py -v

# Strategy tests
pytest tests/add_tests/test_strategy*.py tests/original_tests/test_strategy*.py -v

# Analyzer tests
pytest tests/add_tests/test_analyzer*.py tests/original_tests/test_analyzer*.py -v

# Broker tests
pytest tests/add_tests/test_broker.py -v
```

### Run with Make

```bash
# Run all tests
make test

# Run with coverage
make test-coverage

# Run specific test file
make test-file TEST=tests/add_tests/test_sma.py
```

### Continuous Testing

For development, use pytest-watch for automatic test execution:

```bash
pip install pytest-watch
ptw tests/ -- -v
```

## Best Practices

### DO:

1. **Write tests first** (TDD approach when possible)
2. **Use descriptive test names**: `test_sma_calculates_correctly()` not `test_1()`
3. **Keep tests independent** - no shared state between tests
4. **Use fixtures** for common setup
5. **Mock external dependencies** - API calls, file I/O
6. **Test edge cases** - empty data, minimum period, boundary conditions
7. **Add docstrings** to explain what is being tested
8. **Use markers** for test categorization

### DON'T:

1. **Don't hardcode paths** - use fixtures or relative paths
2. **Don't test implementation details** - test behavior
3. **Don't write monolithic tests** - one assertion per concept
4. **Don't ignore tests** - fix or mark as expected failure
5. **Don't use live data** in unit tests
6. **Don't commit commented-out code**

## Debugging Tests

### Using pdb

```python
def test_failing_case():
    """Test that fails and needs debugging."""
    import pdb; pdb.set_trace()

    cerebro = bt.Cerebro()
    # ... rest of test
```

### Using pytest's pdb

```bash
# Drop into debugger on failure
pytest tests/ --pdb

# Drop into debugger on error (not just failure)
pytest tests/ --pdb --trace
```

### Printing Test Output

```bash
# Show print statements
pytest tests/ -s -v

# Capture output but show on failure
pytest tests/ --capture=no
```

## See Also

- [Development Setup](setup.md)
- [Code Style](style.md)
- [Contributing](contributing.md)
