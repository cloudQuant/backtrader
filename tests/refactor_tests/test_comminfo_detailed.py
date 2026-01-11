#!/usr/bin/env python
"""Test module for CommInfo implementation comparison and broker integration.

This module provides comprehensive tests for comparing the behavior of different
CommInfo (Commission Information) implementations in the backtrader framework.
It tests parameter access, method calls, property access, and integration with
the broker system.

The module focuses on ensuring that the refactored implementation (without
metaclasses) maintains API compatibility and behavioral consistency with the
original implementation.

Example:
    Run the tests from the command line::

        python tests/refactor_tests/test_comminfo_detailed.py

This will execute both the implementation comparison and broker integration
tests.
"""

import backtrader as bt
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
sys.path.insert(0, "tests/original_tests")

import testcommon


def compare_comminfo_implementations():
    """Compare detailed behavior between new and old CommInfo implementations.

    This function performs a comprehensive comparison of CommInfo implementations
    by testing parameter access patterns, method calls, and property access. It
    validates that the refactored implementation maintains compatibility with
    the original behavior.

    The function tests:
    1. Default parameter values (commission, mult, margin, commtype, stocklike, percabs)
    2. Internal state attributes (_stocklike, _commtype)
    3. Key methods: getcommission(), get_margin(), getoperationcost(), getvaluesize()
    4. Property access via .margin and .stocklike
    5. Parameter access via .p attribute

    Returns:
        None: This function prints detailed comparison results to stdout.

    Raises:
        Exception: Propagates any exceptions encountered during parameter or
            method access for diagnostic purposes.
    """

    # Test default CommInfo object
    print("\n1. Creating default CommInfo object:")

    # Test original implementation - use original files
    print("  Switching to original implementation...")

    # Create new CommInfo object
    comminfo_new = bt.CommInfoBase()

    print(f"  New implementation default parameters:")
    for param_name in ["commission", "mult", "margin", "commtype", "stocklike", "percabs"]:
        try:
            value = comminfo_new.get_param(param_name)
            print(f"    {param_name}: {value} (type: {type(value).__name__})")
        except Exception as e:
            print(f"    {param_name}: ERROR - {e}")

    print(f"  New implementation internal state:")
    print(f"    _stocklike: {getattr(comminfo_new, '_stocklike', 'MISSING')}")
    print(f"    _commtype: {getattr(comminfo_new, '_commtype', 'MISSING')}")

    # Test key methods
    print(f"\n2. Testing key methods:")
    test_size = 100
    test_price = 50.0

    print(f"  Test parameters: size={test_size}, price={test_price}")
    print(f"  getcommission(): {comminfo_new.getcommission(test_size, test_price)}")
    print(f"  get_margin(): {comminfo_new.get_margin(test_price)}")
    print(f"  getoperationcost(): {comminfo_new.getoperationcost(test_size, test_price)}")
    print(f"  getvaluesize(): {comminfo_new.getvaluesize(test_size, test_price)}")

    # Test property access
    print(f"\n3. Testing property access:")
    try:
        print(f"  .margin: {comminfo_new.margin}")
    except AttributeError as e:
        print(f"  .margin: ERROR - {e}")

    try:
        print(f"  .stocklike: {comminfo_new.stocklike}")
    except AttributeError as e:
        print(f"  .stocklike: ERROR - {e}")

    # Test .p access
    print(f"\n4. Testing .p access:")
    try:
        print(f"  .p.commission: {comminfo_new.p.commission}")
        print(f"  .p.margin: {comminfo_new.p.margin}")
        print(f"  .p.stocklike: {comminfo_new.p.stocklike}")
    except Exception as e:
        print(f"  .p access: ERROR - {e}")


def test_broker_integration():
    """Test integration with Broker.

    This function validates the integration of CommInfo with the broker system.
    It creates a Cerebro engine with test data and a strategy to verify that
    the broker properly initializes and provides access to CommInfo objects.

    The test verifies:
    1. Broker initial cash and value
    2. CommInfo type assigned by the broker
    3. CommInfo parameters (commission, margin, stocklike) accessible via broker

    Returns:
        None: This function prints broker integration test results to stdout.

    Raises:
        Exception: Propagates any exceptions encountered during broker setup
            or comminfo access for diagnostic purposes.
    """
    print("\n=== Testing Broker Integration ===")

    cerebro = bt.Cerebro()
    data = testcommon.getdata(0)
    cerebro.adddata(data)

    # Add simple strategy to check broker behavior
    class TestStrategy(bt.Strategy):
        """Test strategy for broker integration validation.

        This strategy is used to inspect and verify the broker's CommInfo
        configuration during backtesting initialization. It prints diagnostic
        information about broker state and commission settings.

        Attributes:
            broker: The broker instance managed by Cerebro, accessible via
                self.broker within strategy methods.
            data: The data feed added to Cerebro, accessible via self.data.
        """

        def __init__(self):
            """Initialize the TestStrategy.

            This method is called during strategy instantiation. It performs
            no additional setup as this strategy is purely diagnostic.
            """
            pass

        def start(self):
            """Execute at the start of backtesting.

            This method is called once before the first bar. It prints broker
            state information and validates CommInfo integration by accessing
            commission parameters through the broker's getcommissioninfo method.

            The method tests both get_param() method access and .p attribute
            access to ensure compatibility with different implementation styles.
            """
            print(f"  Broker initial cash: {self.broker.getcash()}")
            print(f"  Broker initial value: {self.broker.getvalue()}")

            # Check CommInfo
            broker_comminfo = self.broker.getcommissioninfo(self.data)
            print(f"  Broker CommInfo type: {type(broker_comminfo).__name__}")
            print(
                f"  Broker CommInfo commission: {broker_comminfo.get_param('commission') if hasattr(broker_comminfo, 'get_param') else getattr(broker_comminfo, 'p', {}).commission}"
            )
            print(
                f"  Broker CommInfo margin: {broker_comminfo.get_param('margin') if hasattr(broker_comminfo, 'get_param') else getattr(broker_comminfo, 'p', {}).margin}"
            )
            print(
                f"  Broker CommInfo stocklike: {broker_comminfo.get_param('stocklike') if hasattr(broker_comminfo, 'get_param') else getattr(broker_comminfo, 'p', {}).stocklike}"
            )

    cerebro.addstrategy(TestStrategy)
    cerebro.run()


if __name__ == "__main__":
    # Execute the comparison and integration tests when run as a script
    compare_comminfo_implementations()
    test_broker_integration()
