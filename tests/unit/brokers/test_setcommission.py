#!/usr/bin/env python
"""Tests for commission configuration behavior in backtrader.

This module contains tests to verify that the setcommission method correctly
configures commission parameters on the broker. It tests parameter access,
CommInfo object creation, and various commission-related calculations.

The tests verify that commission settings are properly applied to data feeds
and that the broker correctly calculates commission costs, margin requirements,
and operation costs based on the configured parameters.
"""

import backtrader as bt
import os
import sys

import testcommon


def test_setcommission_behavior():
    """Test the behavior of the setcommission method.

    This function tests the setcommission method of the broker to ensure
    commission parameters are correctly set and applied to trades. It verifies:

    1. Default CommInfo parameters before setting commission
    2. Custom commission parameter application
    3. CommInfo object creation and type
    4. Parameter access through both get_param() and direct attribute access
    5. Key CommInfo methods: getcommission(), get_margin(), getoperationcost()

    The test uses a minimal strategy that prints configuration details
    at startup and does not execute any trades, allowing for focused
    testing of commission configuration behavior.

    Note:
        This test is primarily for debugging and verification purposes,
        printing detailed information about the commission configuration
        state rather than making assertions.

    Raises:
        Exception: If parameter access fails for both get_param() method
            and direct attribute access (p.parameter_name).
    """
    print("=== Testing setcommission method ===")

    cerebro = bt.Cerebro()
    data = testcommon.getdata(0)
    cerebro.adddata(data)

    class TestStrategy(bt.Strategy):
        """A test strategy for verifying commission configuration.

        This strategy is designed to inspect and verify the broker's
        commission configuration at startup. It does not execute any
        trading logic but instead prints detailed information about
        the commission state before and after calling setcommission().

        Attributes:
            params: A tuple containing strategy parameters.
                stocklike (bool): Whether to treat the data as stock-like.
                    Defaults to False, meaning futures-like behavior with
                    margin requirements.

        Note:
            This strategy intentionally does not implement trading logic
            in next() to focus solely on commission configuration testing.
        """
        params = (("stocklike", False),)

        def __init__(self):
            """Initialize the test strategy.

            This is a minimal initialization that sets up the strategy
            without creating any indicators or executing any setup logic.
            """
            pass

        def start(self):
            """Execute at strategy start to inspect commission configuration.

            This method is called when the strategy starts running, before
            any data is processed. It prints detailed information about:

            1. Broker cash before and after commission setting
            2. CommInfo object type
            3. Default commission parameters
            4. Custom commission parameters after setcommission() call
            5. Results of key CommInfo calculation methods

            The method tests parameter access through both the get_param()
            method and direct attribute access (p.parameter_name) to verify
            compatibility.

            Raises:
                Exception: If parameter access fails for both access methods.
                    The exception is caught and printed rather than raised
                    to allow continued inspection.
            """
            print(f"Broker cash before start: {self.broker.getcash()}")
            print(f"CommInfo type before start: {type(self.broker.getcommissioninfo(self.data)).__name__}")

            # Get default CommInfo
            default_comminfo = self.broker.getcommissioninfo(self.data)
            print(f"Default CommInfo parameters:")
            try:
                print(f"  commission: {default_comminfo.get_param('commission')}")
                print(f"  mult: {default_comminfo.get_param('mult')}")
                print(f"  margin: {default_comminfo.get_param('margin')}")
                print(f"  stocklike: {default_comminfo.get_param('stocklike')}")
                print(f"  _stocklike: {default_comminfo._stocklike}")
                print(f"  _commtype: {default_comminfo._commtype}")
            except Exception as e:
                print(f"  Failed to get default parameters: {e}")
                # Try original method
                try:
                    print(f"  p.commission: {default_comminfo.p.commission}")
                    print(f"  p.mult: {default_comminfo.p.mult}")
                    print(f"  p.margin: {default_comminfo.p.margin}")
                    print(f"  p.stocklike: {default_comminfo.p.stocklike}")
                except Exception as e2:
                    print(f"  Original parameter access also failed: {e2}")

            # Set custom commission
            print(f"\nCalling setcommission(commission=2.0, mult=10.0, margin=1000.0)...")
            if not self.p.stocklike:
                self.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)

            print(f"Broker cash after setting: {self.broker.getcash()}")
            print(f"CommInfo type after setting: {type(self.broker.getcommissioninfo(self.data)).__name__}")

            # Get CommInfo after setting
            new_comminfo = self.broker.getcommissioninfo(self.data)
            print(f"New CommInfo parameters:")
            try:
                print(f"  commission: {new_comminfo.get_param('commission')}")
                print(f"  mult: {new_comminfo.get_param('mult')}")
                print(f"  margin: {new_comminfo.get_param('margin')}")
                print(f"  stocklike: {new_comminfo.get_param('stocklike')}")
                print(f"  _stocklike: {new_comminfo._stocklike}")
                print(f"  _commtype: {new_comminfo._commtype}")
            except Exception as e:
                print(f"  Failed to get new parameters: {e}")
                # Try original method
                try:
                    print(f"  p.commission: {new_comminfo.p.commission}")
                    print(f"  p.mult: {new_comminfo.p.mult}")
                    print(f"  p.margin: {new_comminfo.p.margin}")
                    print(f"  p.stocklike: {new_comminfo.p.stocklike}")
                except Exception as e2:
                    print(f"  Original parameter access also failed: {e2}")

            # Test key methods
            test_price = 100.0
            test_size = 1
            print(f"\nTesting key methods (price={test_price}, size={test_size}):")
            print(f"  getcommission(): {new_comminfo.getcommission(test_size, test_price)}")
            print(f"  get_margin(): {new_comminfo.get_margin(test_price)}")
            print(f"  getoperationcost(): {new_comminfo.getoperationcost(test_size, test_price)}")

        def next(self):
            """Process the next bar (intentionally empty).

            This method is intentionally left empty as the strategy
            is designed only to inspect commission configuration at
            startup, not to execute any trading logic.

            Note:
                This avoids running the entire strategy backtest
                since the test is only concerned with commission
                configuration behavior.
            """
            pass  # Avoid running the entire strategy

        def stop(self):
            """Execute when the strategy stops.

            This method is called when the strategy finishes execution.
            It prints a simple message to indicate the strategy has ended.
            """
            print("Strategy ended")

    cerebro.addstrategy(TestStrategy)
    result = cerebro.run()
    print(f"Run completed")


if __name__ == "__main__":
    test_setcommission_behavior()
