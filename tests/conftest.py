# -*- coding: utf-8 -*-
"""Pytest configuration and shared fixtures for Backtrader test suite.

This module provides common fixtures and configuration for pytest-based testing
of the Backtrader quantitative trading framework. It implements data factories,
engine fixtures, and cleanup hooks to improve test maintainability and isolation.

Fixtures:
    sample_data: Provides a standard data feed for testing
    cerebro_engine: Provides a configured Cerebro engine instance
    clean_env: Automatic cleanup between tests (autouse)

Priority Markers:
    @pytest.mark.priority_p0: Critical tests (core functionality)
    @pytest.mark.priority_p1: High priority (frequently used)
    @pytest.mark.priority_p2: Medium priority (secondary features)
    @pytest.mark.priority_p3: Low priority (nice-to-have)
"""

import pytest
import os
import sys
import tempfile
import shutil
from pathlib import Path

import backtrader as bt
import datetime


# =============================================================================
# Project Root Setup
# =============================================================================

# Get project root directory
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# =============================================================================
# Priority Marker Helpers
# =============================================================================

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "priority_p0: Critical tests - core functionality"
    )
    config.addinivalue_line(
        "markers", "priority_p1: High priority - frequently used features"
    )
    config.addinivalue_line(
        "markers", "priority_p2: Medium priority - secondary features"
    )
    config.addinivalue_line(
        "markers", "priority_p3: Low priority - nice-to-have features"
    )


# =============================================================================
# Path Fixtures
# =============================================================================

@pytest.fixture
def project_root():
    """Return the project root directory path."""
    return _PROJECT_ROOT


@pytest.fixture
def datas_path(project_root):
    """Return the test data directory path."""
    return project_root / "tests" / "datas"


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files.

    The directory is automatically cleaned up after the test.
    """
    temp = tempfile.mkdtemp()
    yield temp
    # Cleanup
    shutil.rmtree(temp, ignore_errors=True)


# =============================================================================
# Data Feed Fixtures
# =============================================================================

@pytest.fixture
def sample_data(datas_path):
    """Provide a standard sample data feed for testing.

    This fixture loads the 2006 daily price data and returns a configured
    BacktraderCSVData feed. The data is pre-configured with standard date
    filtering (full year 2006).

    Returns:
        bt.feeds.BacktraderCSVData: Configured data feed for testing
    """
    datapath = datas_path / "2006-day-001.txt"
    data = bt.feeds.BacktraderCSVData(
        dataname=str(datapath),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )
    return data


@pytest.fixture
def sample_data_multi(datas_path):
    """Provide multiple sample data feeds for multi-data testing.

    Returns:
        list: List of two configured data feeds for 2006
    """
    datafiles = [
        datas_path / "2006-day-001.txt",
        datas_path / "2006-day-002.txt",
    ]

    datas = []
    for datapath in datafiles:
        if datapath.exists():
            data = bt.feeds.BacktraderCSVData(
                dataname=str(datapath),
                fromdate=datetime.datetime(2006, 1, 1),
                todate=datetime.datetime(2006, 12, 31),
            )
            datas.append(data)

    return datas


@pytest.fixture
def week_data(datas_path):
    """Provide weekly sample data feed for testing.

    Returns:
        bt.feeds.BacktraderCSVData: Weekly data feed
    """
    datapath = datas_path / "2006-week-001.txt"
    data = bt.feeds.BacktraderCSVData(
        dataname=str(datapath),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )
    return data


# =============================================================================
# Cerebro Engine Fixtures
# =============================================================================

@pytest.fixture
def cerebro_engine():
    """Provide a basic Cerebro engine instance.

    The engine is created with default settings. Tests can configure
    it further as needed. The engine is automatically cleaned up
    after the test.

    Returns:
        bt.Cerebro: Fresh Cerebro instance for testing
    """
    cerebro = bt.Cerebro()
    yield cerebro
    # Cleanup
    cerebro = None


@pytest.fixture
def cerebro_with_cash(cerebro_engine):
    """Provide a Cerebro engine with initial cash set.

    Args:
        cerebro_engine: Base Cerebro fixture

    Returns:
        bt.Cerebro: Cerebro with 10000.0 initial cash
    """
    cerebro_engine.broker.setcash(10000.0)
    return cerebro_engine


@pytest.fixture
def cerebro_with_data(sample_data, cerebro_engine):
    """Provide a Cerebro engine with data already loaded.

    Args:
        sample_data: Data feed fixture
        cerebro_engine: Cerebro fixture

    Returns:
        bt.Cerebro: Cerebro with data feed added
    """
    cerebro_engine.adddata(sample_data)
    return cerebro_engine


# =============================================================================
# Strategy Fixtures
# =============================================================================

@pytest.fixture
def simple_strategy():
    """Provide a simple test strategy class.

    Returns:
        type: SimpleStrategy class for testing
    """
    class SimpleStrategy(bt.Strategy):
        """A simple moving average crossover trading strategy for testing."""

        params = (
            ("period", 15),
        )

        def __init__(self):
            self.sma = bt.indicators.SMA(self.data, period=self.p.period)

        def next(self):
            if not self.position:
                if self.data.close[0] > self.sma[0]:
                    self.buy()
            elif self.data.close[0] < self.sma[0]:
                self.close()

    return SimpleStrategy


@pytest.fixture
def crossover_strategy():
    """Provide a crossover strategy for testing.

    Returns:
        type: CrossoverStrategy class with CrossOver indicator
    """
    class CrossoverStrategy(bt.Strategy):
        """A crossover strategy using CrossOver indicator for testing."""

        params = (
            ("period", 15),
        )

        def __init__(self):
            self.sma = bt.indicators.SMA(self.data, period=self.p.period)
            self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

        def next(self):
            if not self.position.size:
                if self.cross > 0:
                    self.buy()
            elif self.cross < 0:
                self.close()

    return CrossoverStrategy


# =============================================================================
# Cleanup Fixture (Autouse)
# =============================================================================

@pytest.fixture(autouse=True)
def clean_test_environment():
    """Automatically clean up test environment before and after each test.

    This fixture runs automatically for every test to ensure proper
    isolation. It can be extended to add cleanup logic as needed.
    """
    # Setup before test
    yield
    # Cleanup after test
    # Add any cleanup logic here:
    # - Clear global state
    # - Close open files
    # - Reset singleton instances
    pass


# =============================================================================
# Test Configuration Helpers
# =============================================================================

@pytest.fixture
def test_config():
    """Provide standard test configuration values.

    Returns:
        dict: Dictionary with common test parameters
    """
    return {
        "cash": 10000.0,
        "commission": 0.001,
        "fromdate": datetime.datetime(2006, 1, 1),
        "todate": datetime.datetime(2006, 12, 31),
        "sma_period": 15,
    }


# =============================================================================
# Run Test Helper Fixture
# =============================================================================

@pytest.fixture
def run_cerebro_test():
    """Provide a helper function to run cerebro tests with multiple configurations.

    This mirrors the functionality of testcommon.runtest() but as a pytest
    fixture for better integration.

    Returns:
        callable: Function to run tests with different configurations
    """
    def _run_test(datas, strategy, runonce=None, preload=None, exbar=None, **kwargs):
        """Run a backtest strategy with multiple configuration combinations.

        Args:
            datas: Data feed(s) to use (single or list)
            strategy: Strategy class to test
            runonce: If True, run in runonce mode. If None, test both.
            preload: If True, preload data. If None, test both.
            exbar: Exact bars setting. If None, test multiple values.
            **kwargs: Additional keyword arguments for strategy

        Returns:
            list: List of Cerebro instances, one for each configuration tested
        """
        runonces = [True, False] if runonce is None else [runonce]
        preloads = [True, False] if preload is None else [preload]
        exbars = [-2, -1, False] if exbar is None else [exbar]

        # Handle single data feed
        if isinstance(datas, bt.LineSeries):
            data_list = [datas]
        else:
            data_list = list(datas) if datas else []

        # Store data parameters for recreation
        data_params_list = []
        for data in data_list:
            params = {"dataname": getattr(data, "_dataname", None)}
            if hasattr(data, "p"):
                for pname in ["fromdate", "todate", "timeframe", "compression", "name"]:
                    if hasattr(data.p, pname):
                        params[pname] = getattr(data.p, pname)
            params["data_class"] = data.__class__
            data_params_list.append(params)

        cerebros = []
        for prload in preloads:
            for ronce in runonces:
                for exbar in exbars:
                    cerebro = bt.Cerebro(
                        runonce=ronce, preload=prload, exactbars=exbar
                    )

                    # Create fresh data instances
                    for data_params in data_params_list:
                        data_class = data_params.pop("data_class")
                        new_data = data_class(**data_params)
                        data_params["data_class"] = data_class
                        cerebro.adddata(new_data)

                    cerebro.addstrategy(strategy, **kwargs)
                    cerebro.run()
                    cerebros.append(cerebro)

        return cerebros

    return _run_test


# =============================================================================
# Parametrize Fixtures for Common Test Variations
# =============================================================================

@pytest.fixture(params=[True, False])
def runonce(request):
    """Parametrize runonce mode for testing."""
    return request.param


@pytest.fixture(params=[True, False])
def preload(request):
    """Parametrize preload mode for testing."""
    return request.param


# =============================================================================
# Skipif Conditions
# =============================================================================

def pytest_collection_modifyitems(config, items):
    """Modify collected test items to add markers or skip conditions.

    This function is called after test collection to:
    - Add default priority markers to tests without explicit markers
    - Apply platform-specific skip conditions
    """
    for item in items:
        # Add default P2 marker to tests without priority markers
        if not any(marker.startswith("priority_p") for marker in item.keywords):
            item.add_marker(pytest.mark.priority_p2)
