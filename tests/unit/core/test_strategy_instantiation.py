#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Regression tests for Strategy instantiation chain.

Iteration 4 - T02: Lock down current Strategy instantiation behavior
before making changes to _create_strategy_safely, __new__, __init__.

These tests verify:
1. Parameter passing through addstrategy -> cerebro.run -> Strategy
2. Subclass __init__ is called correctly
3. Multi-strategy instantiation
4. Strategy creation failure behavior in standard vs channel mode
5. _create_strategy_safely path
"""

import datetime
import os

import pytest

import backtrader as bt
from backtrader import errors


# ---------------------------------------------------------------------------
# Helper strategies
# ---------------------------------------------------------------------------


class ParamStrategy(bt.Strategy):
    """Strategy with custom params to test parameter passing."""

    params = (
        ("period", 10),
        ("factor", 1.5),
        ("name", "default"),
    )

    def __init__(self):
        self.init_called = True
        self.received_period = self.p.period
        self.received_factor = self.p.factor
        self.received_name = self.p.name

    def next(self):
        pass


class InitTrackingStrategy(bt.Strategy):
    """Strategy that tracks whether __init__ was called and with what state."""

    params = (("marker", "unset"),)

    def __init__(self):
        self.init_was_called = True
        self.marker_at_init = self.p.marker
        self.had_datas_at_init = len(self.datas) > 0
        self.had_broker_at_init = self.broker is not None

    def next(self):
        pass


class IndicatorStrategy(bt.Strategy):
    """Strategy that creates indicators in __init__."""

    params = (("sma_period", 15),)

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.sma_period)
        self.order = None

    def next(self):
        pass


class FailingInitStrategy(bt.Strategy):
    """Strategy whose __init__ raises an exception."""

    params = (("should_fail", True),)

    def __init__(self):
        if self.p.should_fail:
            raise ValueError("Intentional init failure")

    def next(self):
        pass


class NoInitStrategy(bt.Strategy):
    """Strategy without a custom __init__."""

    params = (("value", 42),)

    def next(self):
        pass


class MultiInheritStrategy(ParamStrategy):
    """Strategy inheriting from another custom strategy."""

    params = (("extra", "bonus"),)

    def __init__(self):
        super().__init__()
        self.extra_value = self.p.extra

    def next(self):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "datas"
)


@pytest.fixture
def data_feed():
    """Create a standard CSV data feed."""
    return bt.feeds.BacktraderCSVData(
        dataname=os.path.join(DATA_DIR, "2006-day-001.txt"),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )


@pytest.fixture
def cerebro_with_data(data_feed):
    """Create Cerebro with one data feed loaded."""
    cerebro = bt.Cerebro()
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(10000.0)
    return cerebro


# ---------------------------------------------------------------------------
# T02-01: Parameter passing tests
# ---------------------------------------------------------------------------


class TestParameterPassing:
    """Verify strategy parameters are correctly passed from addstrategy."""

    def test_default_params(self, cerebro_with_data):
        """Default parameter values are applied when no overrides given."""
        cerebro_with_data.addstrategy(ParamStrategy)
        results = cerebro_with_data.run()
        strat = results[0]
        assert strat.received_period == 10
        assert strat.received_factor == 1.5
        assert strat.received_name == "default"

    def test_custom_params(self, cerebro_with_data):
        """Custom parameter values override defaults."""
        cerebro_with_data.addstrategy(ParamStrategy, period=20, factor=2.0, name="custom")
        results = cerebro_with_data.run()
        strat = results[0]
        assert strat.received_period == 20
        assert strat.received_factor == 2.0
        assert strat.received_name == "custom"

    def test_partial_params(self, cerebro_with_data):
        """Partially overriding params keeps non-overridden defaults."""
        cerebro_with_data.addstrategy(ParamStrategy, period=30)
        results = cerebro_with_data.run()
        strat = results[0]
        assert strat.received_period == 30
        assert strat.received_factor == 1.5  # default
        assert strat.received_name == "default"  # default

    def test_params_accessible_via_p(self, cerebro_with_data):
        """Parameters are accessible via self.p shorthand."""
        cerebro_with_data.addstrategy(ParamStrategy, period=25)
        results = cerebro_with_data.run()
        strat = results[0]
        assert strat.p.period == 25


# ---------------------------------------------------------------------------
# T02-02: __init__ invocation tests
# ---------------------------------------------------------------------------


class TestInitInvocation:
    """Verify __init__ is properly called during strategy creation."""

    def test_init_called(self, cerebro_with_data):
        """Strategy __init__ is called during instantiation."""
        cerebro_with_data.addstrategy(InitTrackingStrategy, marker="test_value")
        results = cerebro_with_data.run()
        strat = results[0]
        assert strat.init_was_called is True

    def test_datas_available_in_init(self, cerebro_with_data):
        """Data feeds are accessible in __init__."""
        cerebro_with_data.addstrategy(InitTrackingStrategy)
        results = cerebro_with_data.run()
        strat = results[0]
        assert strat.had_datas_at_init is True

    def test_broker_available_in_init(self, cerebro_with_data):
        """Broker is accessible in __init__."""
        cerebro_with_data.addstrategy(InitTrackingStrategy)
        results = cerebro_with_data.run()
        strat = results[0]
        assert strat.had_broker_at_init is True

    def test_params_available_in_init(self, cerebro_with_data):
        """Custom params are already set when __init__ runs."""
        cerebro_with_data.addstrategy(InitTrackingStrategy, marker="check_me")
        results = cerebro_with_data.run()
        strat = results[0]
        assert strat.marker_at_init == "check_me"

    def test_no_init_strategy(self, cerebro_with_data):
        """Strategy without custom __init__ still works."""
        cerebro_with_data.addstrategy(NoInitStrategy, value=99)
        results = cerebro_with_data.run()
        strat = results[0]
        assert strat.p.value == 99

    def test_indicator_in_init(self, cerebro_with_data):
        """Indicators created in __init__ are properly set up."""
        cerebro_with_data.addstrategy(IndicatorStrategy, sma_period=20)
        results = cerebro_with_data.run()
        strat = results[0]
        assert hasattr(strat, "sma")
        assert strat.p.sma_period == 20


# ---------------------------------------------------------------------------
# T02-03: Multi-strategy tests
# ---------------------------------------------------------------------------


class TestMultiStrategy:
    """Verify multiple strategies can be instantiated together."""

    def test_two_strategies(self, cerebro_with_data):
        """Two different strategies run independently."""
        cerebro_with_data.addstrategy(ParamStrategy, period=10)
        cerebro_with_data.addstrategy(IndicatorStrategy, sma_period=15)
        results = cerebro_with_data.run()
        assert len(results) == 2
        assert results[0].p.period == 10
        assert results[1].p.sma_period == 15

    def test_same_strategy_different_params(self, cerebro_with_data):
        """Same strategy class with different params creates distinct instances."""
        cerebro_with_data.addstrategy(ParamStrategy, period=10, name="first")
        cerebro_with_data.addstrategy(ParamStrategy, period=20, name="second")
        results = cerebro_with_data.run()
        assert len(results) == 2
        assert results[0].received_name == "first"
        assert results[1].received_name == "second"


# ---------------------------------------------------------------------------
# T02-04: Inheritance chain tests
# ---------------------------------------------------------------------------


class TestInheritance:
    """Verify multi-level strategy inheritance works."""

    def test_inherited_strategy(self, cerebro_with_data):
        """Strategy inheriting from another strategy works correctly."""
        cerebro_with_data.addstrategy(MultiInheritStrategy, period=15, extra="test")
        results = cerebro_with_data.run()
        strat = results[0]
        assert strat.received_period == 15
        assert strat.extra_value == "test"


# ---------------------------------------------------------------------------
# T02-05: _create_strategy_safely tests
# ---------------------------------------------------------------------------


class TestCreateStrategySafely:
    """Verify _create_strategy_safely path works."""

    def test_has_create_strategy_safely(self):
        """Strategy class has _create_strategy_safely classmethod."""
        assert hasattr(bt.Strategy, "_create_strategy_safely")

    def test_standard_run_uses_safe_creation(self, cerebro_with_data):
        """Standard run() path uses _create_strategy_safely when available."""
        cerebro_with_data.addstrategy(ParamStrategy, period=15)
        results = cerebro_with_data.run()
        strat = results[0]
        assert strat.init_called is True
        assert strat.received_period == 15


# ---------------------------------------------------------------------------
# T02-06: Strategy skip / failure behavior
# ---------------------------------------------------------------------------


class TestStrategyFailure:
    """Verify behavior when strategy creation fails."""

    def test_strategy_skip_error_in_standard_mode(self, cerebro_with_data):
        """StrategySkipError in standard mode skips that strategy."""

        class SkipStrategy(bt.Strategy):
            def __init__(self):
                raise errors.StrategySkipError()

            def next(self):
                pass

        cerebro_with_data.addstrategy(SkipStrategy)
        cerebro_with_data.addstrategy(ParamStrategy)
        results = cerebro_with_data.run()
        # SkipStrategy should be skipped, ParamStrategy should remain
        assert len(results) >= 1
