#!/usr/bin/env python

import backtrader as bt
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
sys.path.insert(0, "tests/original_tests")

import testcommon



def compare_comminfo_implementations():
    """Compare detailed behavior between new and old CommInfo implementations.

    This function tests and compares the behavior of CommInfo implementations,
    including parameter access, method calls, and property access.
    """
    print("=== CommInfo Implementation Comparison Analysis ===")

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

    This function tests how CommInfo integrates with the broker system,
    including checking broker cash, value, and commission info settings.
    """
    print("\n=== Testing Broker Integration ===")

    cerebro = bt.Cerebro()
    data = testcommon.getdata(0)
    cerebro.adddata(data)

    # Add simple strategy to check broker behavior
    class TestStrategy(bt.Strategy):
        def __init__(self):
            pass

        def start(self):
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
    compare_comminfo_implementations()
    test_broker_integration()
