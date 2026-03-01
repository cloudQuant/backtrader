#!/usr/bin/env python
"""Test suite for CommInfo system refactoring (Day 44-45).

This module tests the refactored CommInfo system to ensure functional
completeness and backward compatibility are maintained. The tests are
based on known correct behaviors rather than comparisons with the
original implementation.

The CommInfo system handles commission calculations, margin requirements,
and operation costs for different asset types including stocks, futures,
and digital currencies.

Test Categories:
    Base Functionality: Core commission and profit/loss calculations
    Specialized Classes: DC, FuturesPercent, FuturesFixed implementations
    Validation: Parameter validation and edge cases
    Compatibility Logic: Auto-detection and conversion behaviors
    Performance: Parameter access and calculation speed
    Edge Cases: Zero values, automargin, interest calculations
    Documentation: Usage examples and patterns

Example:
    >>> pytest tests/refactor_tests/test_comminfo_refactor.py -v
"""

import datetime
import os
import sys

import pytest

import backtrader as bt

# Import refactored implementation
from backtrader import comminfo as refactored_comminfo


class MockPosition:
    """Mock position object for testing commission calculations.

    Attributes:
        size: Position size (positive for long, negative for short).
        price: Entry price of the position.
        datetime: Timestamp when the position was opened.
    """

    def __init__(self, size, price, datetime_obj=None):
        """Initialize a mock position.

        Args:
            size: Position size (float). Positive for long, negative for short.
            price: Entry price (float).
            datetime_obj: Optional datetime object for the position timestamp.
                Defaults to current time if not provided.
        """
        self.size = size
        self.price = price
        self.datetime = datetime_obj or datetime.datetime.now()


class TestCommInfoBaseFunctionality:
    """Test basic CommInfo functionality.

    These tests verify that the core commission calculation methods
    work correctly for both stock-like and futures-like instruments.
    """

    def test_basic_stock_commission_compatibility(self):
        """Test basic stock commission calculation.

        Verifies that CommissionInfo correctly calculates commission,
        operation cost, position value, and profit/loss for stock-like
        instruments.

        Test calculations:
            - Commission: abs(size) * price * commission_rate
            - Operation cost: abs(size) * price
            - Position value: size * price
            - P&L: size * (new_price - old_price) * multiplier

        Raises:
            AssertionError: If any calculated values don't match expected.
        """
        # Stock-like commission (default behavior)
        comm = refactored_comminfo.CommissionInfo(commission=0.5)

        # Test parameters
        price = 10.0
        size = 100.0

        # For CommissionInfo, percabs=True by default, so commission is used as-is (0.5)
        # Formula: abs(size) * price * commission
        expected_commission = abs(size) * price * 0.5  # 100 * 10 * 0.5 = 500.0
        assert comm.getcommission(size, price) == expected_commission

        # Operation cost for stocks should be size * price
        expected_cost = abs(size) * price  # 100 * 10 = 1000
        assert comm.getoperationcost(size, price) == expected_cost

        # Test position value calculation
        pos = MockPosition(size, price)
        expected_value = size * price  # 100 * 10 = 1000
        assert comm.getvalue(pos, price) == expected_value

        # Test profit and loss
        newprice = 15.0
        expected_pnl = size * (newprice - price) * comm.get_param("mult")  # 100 * (15-10) * 1 = 500
        assert comm.profitandloss(size, price, newprice) == expected_pnl

    def test_futures_commission_compatibility(self):
        """Test futures commission calculation.

        Verifies that CommissionInfo correctly handles futures-like instruments
        with fixed commission per contract and margin requirements.

        Test calculations:
            - Commission: abs(size) * fixed_commission
            - Margin: Fixed margin per contract
            - Operation cost: abs(size) * margin
            - Cash adjustment: size * (new_price - old_price) * multiplier

        Raises:
            AssertionError: If any calculated values don't match expected.
        """
        # Test parameters
        commission = 2.0
        margin = 1000.0
        mult = 10.0

        # Futures-like commission (fixed commission, margin provided)
        comm = refactored_comminfo.CommissionInfo(commission=commission, margin=margin, mult=mult)

        # Test parameters
        price = 2500.0
        size = 5.0

        # For futures-like (fixed commission), commission should be size * commission
        expected_commission = abs(size) * commission  # 5 * 2.0 = 10.0
        assert comm.getcommission(size, price) == expected_commission

        # Margin should return the provided margin
        assert comm.get_margin(price) == margin

        # Operation cost for futures should be size * margin
        expected_cost = abs(size) * margin  # 5 * 1000 = 5000
        assert comm.getoperationcost(size, price) == expected_cost

        # Test cash adjustment for futures
        newprice = 2600.0
        expected_adjustment = size * (newprice - price) * mult  # 5 * (2600-2500) * 10 = 5000
        assert comm.cashadjust(size, price, newprice) == expected_adjustment

    def test_parameter_access_compatibility(self):
        """Test parameter access methods.

        Verifies backward compatibility of parameter access through multiple
        interfaces: .p, .params, and get_param() method.

        Raises:
            AssertionError: If any parameter access returns incorrect values.
        """
        params = {
            "commission": 0.1,  # For CommissionInfo with percabs=True, this stays 0.1
            "mult": 5.0,
            "margin": 500.0,
            "leverage": 2.0,
            "interest": 0.05,
            "percabs": True,
        }

        comm = refactored_comminfo.CommissionInfo(**params)

        # Test .p access (backward compatibility)
        assert comm.p.commission == 0.1  # Stays 0.1 because percabs=True
        assert comm.p.mult == 5.0
        assert comm.p.margin == 500.0
        assert comm.p.leverage == 2.0
        assert comm.p.interest == 0.05
        assert comm.p.percabs == True

        # Test .params access (backward compatibility)
        assert comm.params.commission == 0.1
        assert comm.params.mult == 5.0

        # Test parameter manager access
        assert comm.get_param("commission") == 0.1
        assert comm.get_param("mult") == 5.0

        # Test stocklike property - should be False when margin is provided
        assert comm.stocklike == False

    def test_inheritance_compatibility(self):
        """Test inheritance behavior.

        Verifies that specialized CommInfo classes correctly inherit
        and override parameters from the base classes.

        Raises:
            AssertionError: If inheritance doesn't work as expected.
        """
        # Test CommissionInfo (inherits from bt.CommInfoBase)
        info = refactored_comminfo.CommissionInfo(commission=0.2)

        # Should have percabs=True by default for CommissionInfo
        assert info.p.percabs == True
        # Commission should stay 0.2 because percabs=True (no conversion)
        assert info.p.commission == 0.2

        # Test specialized classes
        dc = refactored_comminfo.ComminfoDC(commission=0.1)

        assert dc.p.stocklike == False
        assert dc.p.percabs == True
        # ComminfoDC should have different default interest
        assert dc.p.interest == 3.0


class TestCommInfoSpecializedClasses:
    """Test specialized CommInfo classes.

    These tests verify the functionality of specialized CommInfo implementations
    for different asset types: digital currencies, futures with percentage-based
    commission, and futures with fixed commission.
    """

    def test_comminfo_dc_functionality(self):
        """Test digital currency CommInfo functionality.

        Verifies that ComminfoDC correctly calculates commission and margin
        for digital currency instruments like Bitcoin.

        DC-specific behavior:
            - Commission: abs(size) * price * multiplier * commission_rate
            - Margin: price * multiplier * margin_rate

        Raises:
            AssertionError: If DC-specific calculations are incorrect.
        """
        params = {"commission": 0.1, "mult": 1.0, "margin": 0.1}

        dc = refactored_comminfo.ComminfoDC(**params)

        price = 50000.0
        size = 0.1

        # Test commission calculation for DC
        # ComminfoDC has percabs=True by default, so commission is used as-is (0.1)
        # ComminfoDC uses formula: abs(size) * price * mult * commission
        expected_commission = (
            abs(size) * price * params["mult"] * params["commission"]
        )  # 0.1 * 50000 * 1.0 * 0.1 = 500.0
        assert dc._getcommission(size, price, False) == expected_commission

        # Test margin calculation for DC
        # DC margin formula: price * mult * margin
        expected_margin = price * params["mult"] * params["margin"]
        assert dc.get_margin(price) == expected_margin

    def test_futures_percent_functionality(self):
        """Test futures percent CommInfo functionality.

        Verifies that ComminfoFuturesPercent correctly calculates commission
        and margin for futures instruments with percentage-based commission.

        FuturesPercent-specific behavior:
            - Commission: abs(size) * price * multiplier * commission_rate
            - Margin: price * multiplier * margin_rate

        Raises:
            AssertionError: If FuturesPercent calculations are incorrect.
        """
        params = {"commission": 0.02, "mult": 10.0, "margin": 0.08}

        fut = refactored_comminfo.ComminfoFuturesPercent(**params)

        price = 3000.0
        size = 2.0

        # Test commission calculation for futures percent
        # ComminfoFuturesPercent has percabs=True by default, so commission is used as-is (0.02)
        # Uses formula: abs(size) * price * mult * commission
        expected_commission = (
            abs(size) * price * params["mult"] * params["commission"]
        )  # 2.0 * 3000 * 10.0 * 0.02 = 1200.0
        assert fut._getcommission(size, price, False) == expected_commission

        # Test margin calculation for futures
        # Futures margin formula: price * mult * margin
        expected_margin = price * params["mult"] * params["margin"]
        assert fut.get_margin(price) == expected_margin

    def test_futures_fixed_functionality(self):
        """Test futures fixed CommInfo functionality.

        Verifies that ComminfoFuturesFixed correctly calculates commission
        and margin for futures instruments with fixed per-contract commission.

        FuturesFixed-specific behavior:
            - Commission: abs(size) * fixed_commission
            - Margin: price * multiplier * margin_rate

        Raises:
            AssertionError: If FuturesFixed calculations are incorrect.
        """
        params = {"commission": 5.0, "mult": 10.0, "margin": 0.08}

        fut = refactored_comminfo.ComminfoFuturesFixed(**params)

        price = 3000.0
        size = 2.0

        # Test commission calculation for futures fixed
        # Uses formula: abs(size) * commission (fixed commission)
        expected_commission = abs(size) * params["commission"]
        assert fut._getcommission(size, price, False) == expected_commission

        # Test margin calculation for futures
        # Futures margin formula: price * mult * margin
        expected_margin = price * params["mult"] * params["margin"]
        assert fut.get_margin(price) == expected_margin


class TestCommInfoValidation:
    """Test parameter validation in refactored CommInfo.

    These tests verify that the refactored CommInfo system properly validates
    input parameters and rejects invalid values with appropriate errors.
    """

    def test_positive_commission_validation(self):
        """Test commission must be non-negative.

        Verifies that commission accepts zero and positive values but
        rejects negative values.

        Raises:
            AssertionError: If validation doesn't work correctly.
        """
        # Should work with positive commission
        comm = refactored_comminfo.CommissionInfo(commission=0.1)
        assert comm.get_param("commission") == 0.1  # Stays 0.1 because percabs=True

        # Should work with zero commission
        comm = refactored_comminfo.CommissionInfo(commission=0.0)
        assert comm.get_param("commission") == 0.0

        # Should reject negative commission
        with pytest.raises(ValueError):
            refactored_comminfo.CommissionInfo(commission=-0.1)

    def test_positive_mult_validation(self):
        """Test mult must be positive.

        Verifies that multiplier accepts positive values but rejects
        zero and negative values.

        Raises:
            AssertionError: If validation doesn't work correctly.
        """
        # Should work with positive mult
        comm = refactored_comminfo.CommissionInfo(mult=2.0)
        assert comm.get_param("mult") == 2.0

        # Should work with small positive mult
        comm = refactored_comminfo.CommissionInfo(mult=0.1)
        assert comm.get_param("mult") == 0.1

        # Should reject zero mult
        with pytest.raises(ValueError):
            refactored_comminfo.CommissionInfo(mult=0.0)

        # Should reject negative mult
        with pytest.raises(ValueError):
            refactored_comminfo.CommissionInfo(mult=-1.0)

    def test_margin_validation(self):
        """Test margin validation.

        Verifies that margin accepts positive values or None, but rejects
        negative values.

        Raises:
            AssertionError: If validation doesn't work correctly.
        """
        # Should work with positive margin
        comm = refactored_comminfo.CommissionInfo(margin=1000.0)
        assert comm.get_param("margin") == 1000.0

        # Should work with None margin (stock-like)
        comm = refactored_comminfo.CommissionInfo(margin=None)
        assert comm.get_param("margin") is None

        # Should reject negative margin
        with pytest.raises(ValueError):
            refactored_comminfo.CommissionInfo(margin=-100.0)

    def test_leverage_validation(self):
        """Test leverage must be positive.

        Verifies that leverage accepts positive values but rejects
        zero and negative values.

        Raises:
            AssertionError: If validation doesn't work correctly.
        """
        # Should work with positive leverage
        comm = refactored_comminfo.CommissionInfo(leverage=2.0)
        assert comm.get_param("leverage") == 2.0

        # Should work with leverage = 1.0
        comm = refactored_comminfo.CommissionInfo(leverage=1.0)
        assert comm.get_param("leverage") == 1.0

        # Should reject zero leverage
        with pytest.raises(ValueError):
            refactored_comminfo.CommissionInfo(leverage=0.0)

        # Should reject negative leverage
        with pytest.raises(ValueError):
            refactored_comminfo.CommissionInfo(leverage=-1.0)


class TestCommInfoCompatibilityLogic:
    """Test complex compatibility logic.

    These tests verify that the refactored system maintains backward
    compatibility through automatic detection and adjustment behaviors.
    """

    def test_commtype_auto_detection(self):
        """Test automatic commtype detection based on margin.

        Verifies that the system automatically detects whether to use
        percentage or fixed commission based on margin parameter.

        Auto-detection rules:
            - margin=None → COMM_PERC, stocklike=True
            - margin provided → COMM_FIXED, stocklike=False

        Raises:
            AssertionError: If auto-detection doesn't work correctly.
        """
        # When margin is None, should be COMM_PERC and stocklike=True
        comm1 = refactored_comminfo.CommInfoBase(margin=None)
        assert comm1._commtype == refactored_comminfo.CommInfoBase.COMM_PERC
        assert comm1._stocklike == True

        # When margin is provided, should be COMM_FIXED and stocklike=False
        comm2 = refactored_comminfo.CommInfoBase(margin=1000.0)
        assert comm2._commtype == refactored_comminfo.CommInfoBase.COMM_FIXED
        assert comm2._stocklike == False

        # When commtype is explicitly set, should use that
        comm3 = refactored_comminfo.CommInfoBase(
            commtype=refactored_comminfo.CommInfoBase.COMM_PERC, stocklike=True
        )
        assert comm3._commtype == refactored_comminfo.CommInfoBase.COMM_PERC
        assert comm3._stocklike == True

    def test_margin_auto_adjustment(self):
        """Test automatic margin adjustment for futures.

        Verifies that margin is automatically set to 1.0 for non-stocklike
        instruments when margin is not provided.

        Raises:
            AssertionError: If auto-adjustment doesn't work correctly.
        """
        # For non-stocklike with no margin, should set margin to 1.0
        comm = refactored_comminfo.CommInfoBase(
            commtype=refactored_comminfo.CommInfoBase.COMM_FIXED, stocklike=False, margin=None
        )
        assert comm.get_param("margin") == 1.0

    def test_commission_percentage_conversion(self):
        """Test commission percentage conversion.

        Verifies that commission rates are automatically converted from
        percentage to decimal when percabs=False.

        Conversion rules:
            - percabs=False, commtype=COMM_PERC → divide by 100
            - percabs=True → no conversion

        Raises:
            AssertionError: If conversion doesn't work correctly.
        """
        # When percabs=False and commtype=COMM_PERC, should divide by 100
        comm = refactored_comminfo.CommInfoBase(
            commission=5.0, commtype=refactored_comminfo.CommInfoBase.COMM_PERC, percabs=False  # 5%
        )
        assert comm.get_param("commission") == 0.05  # Should be converted to 0.05

        # When percabs=True, should not convert
        comm2 = refactored_comminfo.CommInfoBase(
            commission=0.05,  # Already in decimal
            commtype=refactored_comminfo.CommInfoBase.COMM_PERC,
            percabs=True,
        )
        assert comm2.get_param("commission") == 0.05  # Should remain 0.05


class TestCommInfoPerformance:
    """Test performance characteristics of refactored CommInfo.

    These tests verify that the refactored implementation maintains
    acceptable performance for parameter access and calculations.
    """

    def test_parameter_access_performance(self):
        """Test parameter access is performant.

        Verifies that parameter access through get_param() is fast enough
        for high-frequency operations.

        Performance requirements:
            - Median time < 0.15 seconds for 40,000 operations
            - > 75,000 operations per second

        Raises:
            AssertionError: If performance is below threshold.
        """
        import time

        comm = refactored_comminfo.CommissionInfo(
            commission=0.001, mult=2.0, margin=1000.0, leverage=3.0
        )

        # Warm up the parameter access path
        for _ in range(100):
            _ = comm.get_param("commission")
            _ = comm.get_param("mult")
            _ = comm.get_param("margin")
            _ = comm.get_param("leverage")

        # Test parameter access speed with multiple runs for statistical stability
        times = []
        for run in range(3):
            start_time = time.perf_counter()
            for _ in range(10000):
                _ = comm.get_param("commission")
                _ = comm.get_param("mult")
                _ = comm.get_param("margin")
                _ = comm.get_param("leverage")
            end_time = time.perf_counter()
            times.append(end_time - start_time)

        # Use median time for more stable results - adjusted threshold for system characteristics
        total_time = sorted(times)[1]  # median of 3 runs
        assert total_time < 0.15, f"Parameter access too slow: {total_time:.3f}s"

        ops_per_second = 40000 / total_time
        assert ops_per_second > 75000, f"Parameter access too slow: {ops_per_second:.1f} ops/sec"

    def test_commission_calculation_performance(self):
        """Test commission calculation performance.

        Verifies that commission calculations are fast enough for
        high-frequency trading scenarios.

        Performance requirements:
            - Median time < 0.2 seconds for 10,000 operations
            - > 10,000 operations per second

        Raises:
            AssertionError: If performance is below threshold.
        """
        import time

        comm = refactored_comminfo.CommissionInfo(commission=0.001)

        # Warm up the calculation path with extended warmup for better performance stability
        for _ in range(500):
            comm.getcommission(100.0, 50.0)

        # Test commission calculation speed with multiple runs for statistical stability
        times = []
        for run in range(5):
            start_time = time.perf_counter()
            for _ in range(10000):
                comm.getcommission(100.0, 50.0)
            end_time = time.perf_counter()
            times.append(end_time - start_time)

        # Use median time for more stable results - adjusted threshold for system characteristics
        total_time = sorted(times)[2]  # median of 5 runs
        assert total_time < 0.2, f"Commission calculation too slow: {total_time:.3f}s"

        ops_per_second = 10000 / total_time
        assert (
            ops_per_second > 10000
        ), f"Commission calculation too slow: {ops_per_second:.1f} ops/sec"


class TestCommInfoEdgeCases:
    """Test edge cases and error conditions.

    These tests verify correct behavior for unusual inputs and
    special calculation modes.
    """

    def test_zero_size_operations(self):
        """Test operations with zero size.

        Verifies that operations with zero size correctly return zero
        commission and operation cost.

        Raises:
            AssertionError: If zero-size operations don't return zero.
        """
        comm = refactored_comminfo.CommissionInfo(commission=0.001)

        # Zero size should result in zero commission
        assert comm.getcommission(0.0, 100.0) == 0.0
        assert comm.getoperationcost(0.0, 100.0) == 0.0

    def test_automargin_calculation(self):
        """Test automargin calculation modes.

        Verifies that automargin parameter correctly controls margin
        calculation in different modes.

        Automargin modes:
            - automargin=False: Use margin parameter directly
            - automargin < 0: Use mult * price
            - automargin > 0: Use automargin * price

        Raises:
            AssertionError: If automargin calculations are incorrect.
        """
        price = 1000.0

        # automargin = False, should use margin parameter
        comm1 = refactored_comminfo.CommInfoBase(margin=500.0, automargin=False)
        assert comm1.get_margin(price) == 500.0

        # automargin < 0, should use mult * price
        comm2 = refactored_comminfo.CommInfoBase(mult=2.0, automargin=-1.0)
        assert comm2.get_margin(price) == 2000.0  # 2.0 * 1000.0

        # automargin > 0, should use automargin * price
        comm3 = refactored_comminfo.CommInfoBase(automargin=0.1)
        assert comm3.get_margin(price) == 100.0  # 0.1 * 1000.0

    def test_interest_calculation(self):
        """Test interest calculation edge cases.

        Verifies that interest calculations work correctly for short
        positions with credit rates.

        Interest calculation:
            - Credit rate: annual_rate / 365
            - Interest: days * credit_rate * abs(size) * price

        Raises:
            AssertionError: If interest calculations are incorrect.
        """
        comm = refactored_comminfo.CommInfoBase(interest=0.05)  # 5% annual

        # Test internal credit rate calculation
        assert comm._creditrate == 0.05 / 365.0

        # Mock data for interest calculation
        pos = MockPosition(-100.0, 50.0, datetime.datetime(2023, 1, 1))
        current_dt = datetime.datetime(2023, 1, 11)  # 10 days later

        # Should calculate interest for 10 days
        interest = comm._get_credit_interest(
            None, -100.0, 50.0, 10, current_dt.date(), pos.datetime.date()
        )
        expected = 10 * (0.05 / 365.0) * 100.0 * 50.0  # 10 days * rate * abs(size) * price
        assert abs(interest - expected) < 0.01


class TestCommInfoDocumentationAndUsage:
    """Test usage patterns and documentation examples.

    These tests verify that the documented usage patterns work correctly
    and serve as executable examples.
    """

    def test_basic_usage_example(self):
        """Test basic usage example from documentation.

        Demonstrates creating a commission info object for stocks
        and calculating basic commission and cost.

        Raises:
            AssertionError: If example doesn't work as documented.
        """
        # Create a commission info for stocks with 0.1% commission
        comm = refactored_comminfo.CommissionInfo(commission=0.001)

        # Calculate commission for buying 100 shares at $50 each
        commission = comm.getcommission(100, 50.0)
        assert commission == 5.0  # 100 * 50 * 0.001

        # Calculate operation cost
        cost = comm.getoperationcost(100, 50.0)
        assert cost == 5000.0  # 100 * 50 (for stocks)

    def test_futures_usage_example(self):
        """Test futures usage example.

        Demonstrates creating a commission info object for futures
        with margin requirements.

        Raises:
            AssertionError: If example doesn't work as documented.
        """
        # Create futures commission with margin
        comm = refactored_comminfo.CommissionInfo(
            commission=2.0,  # $2 per contract
            margin=1000.0,  # $1000 margin per contract
            mult=10.0,  # $10 per point
        )

        # Calculate commission for 5 contracts
        commission = comm.getcommission(5, 2500.0)
        assert commission == 10.0  # 5 * 2.0

        # Calculate operation cost (uses margin for futures)
        cost = comm.getoperationcost(5, 2500.0)
        assert cost == 5000.0  # 5 * 1000.0


def test_comprehensive_compatibility():
    """Run comprehensive compatibility test suite.

    This function executes all test categories in sequence to verify
    complete compatibility of the refactored CommInfo system.

    Prints:
        Progress messages and completion status for each test category.

    Example:
        >>> test_comprehensive_compatibility()
        Running comprehensive CommInfo compatibility tests...
        Testing basic functionality compatibility
        Testing specialized class compatibility
        ...
    """
    print("\nRunning comprehensive CommInfo compatibility tests...")

    # Test original functionality preservation
    print("Testing basic functionality compatibility")
    test_basic = TestCommInfoBaseFunctionality()
    test_basic.test_basic_stock_commission_compatibility()
    test_basic.test_futures_commission_compatibility()
    test_basic.test_parameter_access_compatibility()
    test_basic.test_inheritance_compatibility()

    # Test specialized classes
    print("Testing specialized class compatibility")
    test_special = TestCommInfoSpecializedClasses()
    test_special.test_comminfo_dc_functionality()
    test_special.test_futures_percent_functionality()
    test_special.test_futures_fixed_functionality()

    # Test validation improvements
    print("Testing parameter validation")
    test_validation = TestCommInfoValidation()
    test_validation.test_positive_commission_validation()
    test_validation.test_positive_mult_validation()
    test_validation.test_margin_validation()
    test_validation.test_leverage_validation()

    # Test compatibility logic
    print("Testing compatibility logic")
    test_compat = TestCommInfoCompatibilityLogic()
    test_compat.test_commtype_auto_detection()
    test_compat.test_margin_auto_adjustment()
    test_compat.test_commission_percentage_conversion()

    # Test performance
    print("Testing performance characteristics")
    test_perf = TestCommInfoPerformance()
    test_perf.test_parameter_access_performance()
    test_perf.test_commission_calculation_performance()

    # Test edge cases
    print("Testing edge cases")
    test_edge = TestCommInfoEdgeCases()
    test_edge.test_zero_size_operations()
    test_edge.test_automargin_calculation()
    test_edge.test_interest_calculation()

    # Test usage examples
    print("Testing usage examples")
    test_usage = TestCommInfoDocumentationAndUsage()
    test_usage.test_basic_usage_example()
    test_usage.test_futures_usage_example()

    print("\nAll CommInfo compatibility tests passed!")


if __name__ == "__main__":
    test_comprehensive_compatibility()
    pytest.main([__file__, "-v"])
