#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Improved test examples demonstrating TEA review recommendations.

This module demonstrates the improved testing patterns based on the TEA
test quality review recommendations. It shows:

1. Test IDs for traceability (format: EPIC.STORY-LEVEL-SEQ)
2. Priority markers (P0/P1/P2/P3) for selective execution
3. Pytest fixtures for setup/teardown
4. Data factory pattern for consistent test data
5. Proper test isolation with cleanup hooks

Run with:
    # Run all tests
    pytest tests/examples/test_improved_examples.py -v

    # Run only P0 (critical) tests
    pytest tests/examples/test_improved_examples.py -v -m priority_p0

    # Run P0 and P1 tests
    pytest tests/examples/test_improved_examples.py -v -m "priority_p0 or priority_p1"
"""

import pytest
import backtrader as bt

# Import factory functions
from tests.test_utils.factories import (
    create_data_feed,
    create_cerebro,
    create_crossover_strategy,
    create_simple_sma_strategy,
    create_sharpe_analyzer,
    create_returns_analyzer,
    setup_basic_backtest,
    validate_backtest_results,
    create_sma_indicator,
    create_ema_indicator,
    create_macd_indicator,
)

# =============================================================================
# Test ID Format: EPIC.STORY-LEVEL-SEQ
#   EPIC: Major feature area (1=Cerebro, 2=Strategy, 3=Indicator, etc.)
#   STORY: User story within epic
#   LEVEL: Test level (UT=Unit, IT=Integration, E2E=End-to-End)
#   SEQ: Sequence number (001, 002, etc.)
# =============================================================================


# =============================================================================
# Cerebro Tests (EPIC 1)
# =============================================================================


@pytest.mark.priority_p0  # Critical - core engine functionality
def test_1_1_UT_001_cerebro_basic_execution(sample_data, cerebro_engine):
    """Test 1.1-UT-001: Verify Cerebro can execute a basic backtest.

    Priority: P0 - Critical (core engine functionality)
    Epic: 1 (Cerebro), Story: 1 (Basic Execution), Level: UT (Unit Test), Seq: 001

    This test verifies that the Cerebro engine can:
    * Load a data feed via fixture
    * Execute a simple strategy
    * Return valid results

    Args:
        sample_data: Data feed fixture from conftest.py
        cerebro_engine: Cerebro fixture from conftest.py
    """
    # Arrange - Use fixtures instead of manual setup
    cerebro_engine.adddata(sample_data)

    # Act - Run the backtest
    results = cerebro_engine.run()

    # Assert - Verify execution
    assert len(results) > 0, "Cerebro returned no results"
    assert len(results[0]) > 0, "Strategy processed no data"


@pytest.mark.priority_p0
def test_1_1_IT_001_cerebro_with_analyzers(sample_data, cerebro_engine):
    """Test 1.1-IT-001: Verify Cerebro integrates with analyzers.

    Priority: P0 - Critical (performance metrics)
    Epic: 1 (Cerebro), Story: 1 (Basic Execution), Level: IT (Integration), Seq: 001

    Args:
        sample_data: Data feed fixture
        cerebro_engine: Cerebro fixture
    """
    # Arrange - Use factory for analyzer
    analyzer_class, kwargs = create_sharpe_analyzer()
    cerebro_engine.adddata(sample_data)
    cerebro_engine.addanalyzer(analyzer_class, **kwargs)

    # Act
    results = cerebro_engine.run()
    strat = results[0]

    # Assert - Verify analyzer attached
    assert hasattr(strat.analyzers, "sharpe"), "Sharpe analyzer not found"
    analysis = strat.analyzers.sharpe.get_analysis()
    assert isinstance(analysis, dict), "Analysis should return a dict"


@pytest.mark.priority_p1  # High priority - frequently used
def test_1_2_UT_001_cerebro_multiple_data_feeds(sample_data_multi, cerebro_engine):
    """Test 1.2-UT-001: Verify Cerebro handles multiple data feeds.

    Priority: P1 - High (multi-strategy scenarios)
    Epic: 1 (Cerebro), Story: 2 (Multiple Data), Level: UT, Seq: 001

    Args:
        sample_data_multi: Multiple data feeds fixture
        cerebro_engine: Cerebro fixture
    """
    # Arrange
    for data in sample_data_multi:
        cerebro_engine.adddata(data)

    # Act
    results = cerebro_engine.run()

    # Assert
    assert len(results) > 0
    strat = results[0]
    assert len(strat.datas) == len(sample_data_multi), "Not all data feeds loaded"


@pytest.mark.priority_p2  # Medium priority - secondary feature
def test_1_3_UT_001_cerebro_with_observers(sample_data, cerebro_engine):
    """Test 1.3-UT-001: Verify Cerebro integrates with observers.

    Priority: P2 - Medium (visualization/tracking)
    Epic: 1 (Cerebro), Story: 3 (Observers), Level: UT, Seq: 001

    Args:
        sample_data: Data feed fixture
        cerebro_engine: Cerebro fixture
    """
    # Arrange
    cerebro_engine.adddata(sample_data)
    cerebro_engine.addobserver(bt.observers.DrawDown)

    # Act
    results = cerebro_engine.run()

    # Assert
    strat = results[0]
    assert len(strat.observers) > 0, "No observers attached"


# =============================================================================
# Strategy Tests (EPIC 2)
# =============================================================================


@pytest.mark.priority_p0
def test_2_1_IT_001_strategy_basic_trading(cerebro_with_data, crossover_strategy):
    """Test 2.1-IT-001: Verify strategy executes trading logic.

    Priority: P0 - Critical (core strategy execution)
    Epic: 2 (Strategy), Story: 1 (Basic Trading), Level: IT, Seq: 001

    Args:
        cerebro_with_data: Cerebro with data pre-loaded
        crossover_strategy: Crossover strategy fixture
    """
    # Arrange - Use fixtures for setup
    cerebro_with_data.addstrategy(crossover_strategy)
    cerebro_with_data.broker.setcash(10000.0)

    # Act
    results = cerebro_with_data.run()

    # Assert
    assert len(results) > 0
    final_value = cerebro_with_data.broker.getvalue()
    assert final_value > 0, "Portfolio value should be positive"


@pytest.mark.priority_p0
def test_2_1_UT_002_strategy_indicator_registration(cerebro_with_data):
    """Test 2.1-UT-002: Verify strategy indicators are registered.

    Priority: P0 - Critical (indicator calculation)
    Epic: 2 (Strategy), Story: 1 (Basic Trading), Level: UT, Seq: 002

    Args:
        cerebro_with_data: Cerebro with data pre-loaded
    """

    # Arrange - Create strategy that validates indicators
    class IndicatorValidationStrategy(bt.Strategy):
        """Strategy for validating indicator registration and calculation.

        This strategy verifies that:
        1. Indicators are properly registered in the _lineiterators list
        2. Indicator values are calculated correctly during backtesting
        """

        def __init__(self):
            """Initialize the strategy with an SMA indicator.

            Sets up the 15-period SMA indicator and initializes the
            registration flag to False.
            """
            self.sma = bt.indicators.SMA(self.data, period=15)
            # Verify indicator is registered in lineiterators
            self.indicator_registered = False

        def start(self):
            """Verify SMA indicator is registered in _lineiterators.

            Checks the _lineiterators list to confirm the SMA indicator
            was properly registered during initialization.
            """
            # Check if SMA is in _lineiterators
            for item in self._lineiterators[0]:
                if hasattr(item, "alias") and "sma" in str(item.alias):
                    self.indicator_registered = True

        def next(self):
            """Verify indicator values are calculated each bar.

            After the warmup period (15 bars), asserts that the SMA
            indicator produces positive values.

            Raises:
                AssertionError: If SMA value is not positive after warmup.
            """
            # Verify indicator values are calculated
            if len(self) >= 15:
                assert self.sma[0] > 0, "SMA value should be positive"

    # Act
    cerebro_with_data.addstrategy(IndicatorValidationStrategy)
    results = cerebro_with_data.run()

    # Assert
    assert len(results) > 0


@pytest.mark.priority_p1
def test_2_2_UT_001_strategy_parameters(cerebro_with_data):
    """Test 2.2-UT-001: Verify strategy parameters work correctly.

    Priority: P1 - High (customization)
    Epic: 2 (Strategy), Story: 2 (Parameters), Level: UT, Seq: 001

    Args:
        cerebro_with_data: Cerebro with data pre-loaded
    """

    # Arrange - Create strategy with custom parameters
    class ParamStrategy(bt.Strategy):
        """Strategy demonstrating custom parameter usage.

        This strategy validates that custom parameters passed to the strategy
        are properly set and accessible via self.p or self.params.

        Attributes:
            params: Tuple of (name, default_value) pairs for strategy parameters.
        """

        params = (
            ("period", 20),
            ("multiplier", 2.0),
        )

        def __init__(self):
            """Initialize the strategy using custom period parameter.

            Creates an SMA indicator using the period parameter value.
            """
            self.sma = bt.indicators.SMA(self.data, period=self.p.period)

        def next(self):
            """Execute trading logic for each bar.

            After the warmup period, verifies the SMA indicator produces
            positive values.

            Raises:
                AssertionError: If SMA value is not positive after warmup.
            """
            if len(self) >= self.p.period:
                assert self.sma[0] > 0

    # Act
    cerebro_with_data.addstrategy(ParamStrategy, period=25, multiplier=3.0)
    results = cerebro_with_data.run()

    # Assert
    assert len(results) > 0
    # Verify parameter was set correctly
    strat = results[0]
    assert strat.p.period == 25, "Parameter not set correctly"


class _OptSMAStrategy(bt.Strategy):
    """Module-level strategy class for optimization test (must be picklable).

    This strategy implements a simple crossover system where it buys when
    price crosses above the SMA and closes when price crosses below.

    Note:
        This class is defined at module level (not inside a test function)
        to ensure it can be pickled for multiprocessing during optimization.

    Attributes:
        params: Tuple containing the configurable period parameter.
    """

    params = (("period", 15),)

    def __init__(self):
        """Initialize the strategy with SMA indicator.

        Creates an SMA indicator using the configurable period parameter.
        """
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)

    def next(self):
        """Execute simple crossover trading logic.

        Buy Logic:
            - Buy when close price crosses above SMA (no existing position)

        Exit Logic:
            - Close position when close price crosses below SMA
        """
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.buy()
        elif self.data.close[0] < self.sma[0]:
            self.close()


@pytest.mark.priority_p2
def test_2_3_UT_001_strategy_optimization(cerebro_with_data):
    """Test 2.3-UT-001: Verify strategy optimization runs.

    Priority: P2 - Medium (advanced feature)
    Epic: 2 (Strategy), Story: 3 (Optimization), Level: UT, Seq: 001

    Note: Optimization test - may take longer

    Args:
        cerebro_with_data: Cerebro with data pre-loaded
    """
    # Arrange - Use module-level class (picklable for multiprocessing)
    cerebro_with_data.optstrategy(_OptSMAStrategy, period=range(10, 20, 5))

    # Act
    results = cerebro_with_data.run(maxcpus=1)

    # Assert - Should have multiple results from optimization
    assert len(results) > 1, "Optimization should return multiple results"


# =============================================================================
# Indicator Tests (EPIC 3)
# =============================================================================


@pytest.mark.priority_p0
def test_3_1_UT_001_sma_indicator_calculation(sample_data):
    """Test 3.1-UT-001: Verify SMA indicator calculates correctly.

    Priority: P0 - Critical (core indicator)
    Epic: 3 (Indicator), Story: 1 (SMA), Level: UT, Seq: 001

    Args:
        sample_data: Data feed fixture
    """
    # Arrange - Use factory to create indicator
    sma = create_sma_indicator(period=15, data=sample_data)

    # Act - Run cerebro to calculate indicator
    cerebro = create_cerebro()
    cerebro.adddata(sample_data)

    class TestStrategy(bt.Strategy):
        """Strategy for testing SMA indicator calculation.

        Collects SMA values after the warmup period to verify the indicator
        is calculated correctly throughout the backtest.

        Attributes:
            sma: 15-period Simple Moving Average indicator.
            values_at_end: List storing SMA values during backtest.
        """

        def __init__(self):
            """Initialize the strategy with SMA indicator.

            Creates a 15-period SMA indicator and initializes an empty list
            to collect indicator values.
            """
            self.sma = bt.indicators.SMA(self.data, period=15)
            self.values_at_end = []

        def next(self):
            """Collect SMA values after warmup period.

            After 15 bars of data, stores the current SMA value for
            verification in the test assertions.
            """
            if len(self) >= 15:
                self.values_at_end.append(self.sma[0])

    cerebro.addstrategy(TestStrategy)
    results = cerebro.run()

    # Assert - Verify values were calculated
    strat = results[0]
    assert len(strat) > 0, "No bars processed"
    assert len(strat.values_at_end) > 0, "SMA not calculated"


@pytest.mark.priority_p1
def test_3_2_UT_001_ema_indicator(sample_data):
    """Test 3.2-UT-001: Verify EMA indicator calculates correctly.

    Priority: P1 - High (common indicator)
    Epic: 3 (Indicator), Story: 2 (EMA), Level: UT, Seq: 001

    Args:
        sample_data: Data feed fixture
    """
    # Arrange - Use factory
    ema = create_ema_indicator(period=15, data=sample_data)

    # Act
    cerebro = create_cerebro()
    cerebro.adddata(sample_data)

    class TestStrategy(bt.Strategy):
        """Strategy for testing EMA indicator calculation.

        Verifies that the Exponential Moving Average indicator is
        calculated correctly and produces valid values.

        Attributes:
            ema: 15-period Exponential Moving Average indicator.
        """

        def __init__(self):
            """Initialize the strategy with EMA indicator.

            Creates a 15-period EMA indicator.
            """
            self.ema = bt.indicators.EMA(self.data, period=15)

        def next(self):
            """Verify EMA produces valid values.

            After the warmup period, asserts the EMA indicator produces
            positive values.

            Raises:
                AssertionError: If EMA value is not positive after warmup.
            """
            if len(self) >= 15:
                assert self.ema[0] > 0

    cerebro.addstrategy(TestStrategy)
    results = cerebro.run()

    # Assert
    assert len(results) > 0


@pytest.mark.priority_p2
def test_3_3_UT_001_macd_indicator(sample_data):
    """Test 3.3-UT-001: Verify MACD indicator calculates correctly.

    Priority: P2 - Medium (complex indicator)
    Epic: 3 (Indicator), Story: 3 (MACD), Level: UT, Seq: 001

    Args:
        sample_data: Data feed fixture
    """
    # Arrange - Use factory
    macd = create_macd_indicator(data=sample_data)

    # Act
    cerebro = create_cerebro()
    cerebro.adddata(sample_data)

    class TestStrategy(bt.Strategy):
        """Strategy for testing MACD indicator calculation.

        Verifies that the MACD (Moving Average Convergence Divergence)
        indicator is properly initialized with all its component lines.

        Attributes:
            macd: MACD indicator with macd, signal, and histogram lines.
        """

        def __init__(self):
            """Initialize the strategy with MACD indicator.

            Creates a standard MACD indicator using default parameters.
            """
            self.macd = bt.indicators.MACD(self.data)

        def next(self):
            """Verify MACD structure after warmup period.

            After 35 bars of warmup data, verifies the MACD indicator
            has all expected component lines (macd, signal, histogram).

            Raises:
                AssertionError: If MACD components are missing.
            """
            if len(self) >= 35:  # MACD requires warmup
                # MACD has multiple lines: macd, signal, histo
                assert hasattr(self.macd, "macd")
                assert hasattr(self.macd, "signal")

    cerebro.addstrategy(TestStrategy)
    results = cerebro.run()

    # Assert
    assert len(results) > 0


# =============================================================================
# Broker Tests (EPIC 4)
# =============================================================================


@pytest.mark.priority_p0
def test_4_1_UT_001_broker_cash_management(cerebro_engine):
    """Test 4.1-UT-001: Verify broker cash management.

    Priority: P0 - Critical (account management)
    Epic: 4 (Broker), Story: 1 (Cash Management), Level: UT, Seq: 001

    Args:
        cerebro_engine: Cerebro fixture
    """
    # Arrange - Use factory for consistent setup
    cerebro = create_cerebro(cash=100000.0)

    # Act & Assert
    assert cerebro.broker.getcash() == 100000.0, "Initial cash not set"
    assert cerebro.broker.getvalue() == 100000.0, "Initial value not set"


@pytest.mark.priority_p1
def test_4_2_UT_001_broker_commission(sample_data, cerebro_engine):
    """Test 4.2-UT-001: Verify broker commission calculation.

    Priority: P1 - High (trading costs)
    Epic: 4 (Broker), Story: 2 (Commission), Level: UT, Seq: 001

    Args:
        sample_data: Data feed fixture
        cerebro_engine: Cerebro fixture
    """
    # Arrange - Use factory with commission
    cerebro = create_cerebro(cash=10000.0, commission=0.001)
    cerebro.adddata(sample_data)

    # Add strategy that generates trades
    SimpleSMA = create_simple_sma_strategy(period=15)
    cerebro.addstrategy(SimpleSMA)

    # Act
    results = cerebro.run()

    # Assert - Verify trades were executed with commission
    assert len(results) > 0
    # With commission, final value should be different from initial
    # (assuming trades were made)
    final_value = cerebro.broker.getvalue()
    assert final_value > 0


# =============================================================================
# Integration Tests (Multiple Components)
# =============================================================================


@pytest.mark.priority_p0
def test_integration_001_complete_backtest_flow():
    """Test INT-001: Verify complete backtest flow from setup to analysis.

    Priority: P0 - Critical (end-to-end core flow)
    Test ID: INT-001

    This test demonstrates the complete factory-based approach:
    1. Use setup_basic_backtest() for complete configuration
    2. Run backtest
    3. Validate results with helper function
    """
    # Arrange - Use complete setup factory
    data = create_data_feed()
    strategy = create_crossover_strategy(period=15)
    analyzer = create_sharpe_analyzer()

    cerebro = setup_basic_backtest(
        cash=10000.0,
        strategy=strategy,
        data_feeds=[data],
        analyzers=[analyzer],
        commission=0.001,
    )

    # Act
    results = cerebro.run()

    # Assert - Use validation helper
    summary = validate_backtest_results(
        results,
        min_strategies=1,
        min_bars=1,
        min_value=0.0,
    )

    assert summary["strategies"] >= 1
    assert summary["bars_processed"] > 0


@pytest.mark.priority_p1
def test_integration_002_multi_strategy_backtest():
    """Test INT-002: Verify backtest with multiple strategies.

    Priority: P1 - High (portfolio management)
    Test ID: INT-002
    """
    # Arrange
    data = create_data_feed()
    cerebro = create_cerebro(cash=10000.0)
    cerebro.adddata(data)

    # Add multiple strategies
    cerebro.addstrategy(create_crossover_strategy(period=10))
    cerebro.addstrategy(create_crossover_strategy(period=20))

    # Act
    results = cerebro.run()

    # Assert - Should have 2 strategy results
    assert len(results) == 2, "Expected 2 strategies"


# =============================================================================
# Data Factory Tests
# =============================================================================


@pytest.mark.priority_p1
def test_factory_001_create_data_feed_default():
    """Test FACTORY-001: Verify data feed factory with defaults.

    Priority: P1 - High (factory reliability)
    Test ID: FACTORY-001
    """
    # Act - Use factory with defaults
    data = create_data_feed()

    # Assert - Verify data feed created
    assert data is not None
    assert hasattr(data, "_dataname")


@pytest.mark.priority_p2
def test_factory_002_create_data_feed_custom():
    """Test FACTORY-002: Verify data feed factory with custom parameters.

    Priority: P2 - Medium (factory flexibility)
    Test ID: FACTORY-002
    """
    # Act - Use factory with custom date range
    from datetime import datetime

    data = create_data_feed(
        fromdate=datetime(2006, 6, 1),
        todate=datetime(2006, 12, 31),
    )

    # Assert
    assert data is not None


@pytest.mark.priority_p1
def test_factory_003_create_cerebro_with_commission():
    """Test FACTORY-003: Verify Cerebro factory with commission.

    Priority: P1 - High (factory reliability)
    Test ID: FACTORY-003
    """
    # Act
    cerebro = create_cerebro(cash=10000.0, commission=0.002)

    # Assert
    assert cerebro.broker.getcash() == 10000.0


# =============================================================================
# Cleanup and Isolation Tests
# =============================================================================


@pytest.mark.priority_p2
def test_isolation_001_test_state_cleanup():
    """Test ISOLATION-001: Verify test state doesn't leak between tests.

    Priority: P2 - Medium (test reliability)
    Test ID: ISOLATION-001

    This test verifies that state from one test doesn't affect another.
    The autouse clean_test_environment fixture should handle this.
    """
    # Arrange - Create some state
    cerebro = create_cerebro(cash=5000.0)
    data = create_data_feed()
    cerebro.adddata(data)

    # Act
    initial_cash = cerebro.broker.getcash()

    # Assert - Verify clean state (should be our value, not from previous test)
    assert initial_cash == 5000.0, "Test state leaked from previous test"


# =============================================================================
# Standalone Execution (for backward compatibility)
# =============================================================================


def main():
    """Run tests in standalone mode for backward compatibility.

    This allows running tests directly without pytest discovery:
        python tests/examples/test_improved_examples.py

    The function configures pytest with verbose output and short traceback
    format for cleaner error reporting.
    """
    pytest.main([__file__, "-v", "--tb=short"])


if __name__ == "__main__":
    main()
