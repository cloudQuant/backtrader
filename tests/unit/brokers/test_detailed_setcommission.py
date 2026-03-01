#!/usr/bin/env python
"""Detailed test for CommInfo parameter setting process.

This module tests the detailed process of creating and configuring
CommInfo (Commission Info) objects, which handle commission calculations
and margin requirements in backtrader.
"""

import backtrader as bt
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
sys.path.insert(0, "tests/original_tests")

import testcommon



def test_parameter_setting_details():
    """Test detailed parameter setting process for CommInfo.

    This test verifies that CommInfo objects can be created with
    custom parameters and that those parameters are correctly
    stored and accessible.
    """
    print("=== Detailed CommInfo Parameter Setting Test ===")

    # 1. Test direct CommInfo object creation
    print("\n1. Direct CommInfo object creation (similar to broker.setcommission):")
    print("   Call: bt.CommInfoBase(commission=2.0, margin=1000.0, mult=10.0)")

    try:
        comminfo = bt.CommInfoBase(commission=2.0, margin=1000.0, mult=10.0)
        print(f"   Creation successful!")
        print(f"   commission: {comminfo.get_param('commission')}")
        print(f"   margin: {comminfo.get_param('margin')}")
        print(f"   mult: {comminfo.get_param('mult')}")
        print(f"   stocklike: {comminfo.get_param('stocklike')}")
        print(f"   _stocklike: {comminfo._stocklike}")
        print(f"   _commtype: {comminfo._commtype}")
        print(f"   property stocklike: {comminfo.stocklike}")
        print(f"   property margin: {comminfo.margin}")

        # Test key methods
        test_price = 100.0
        test_size = 1
        print(f"\n   Test key methods (price={test_price}, size={test_size}):")
        print(f"   getcommission(): {comminfo.getcommission(test_size, test_price)}")
        print(f"   get_margin(): {comminfo.get_margin(test_price)}")
        print(f"   getoperationcost(): {comminfo.getoperationcost(test_size, test_price)}")

    except Exception as e:
        print(f"   Creation failed: {e}")
        import traceback

        traceback.print_exc()

    # 2. Test creation with default parameters (for comparison)
    print("\n\n2. Test creation with default parameters:")
    print("   Call: bt.CommInfoBase()")

    try:
        default_comminfo = bt.CommInfoBase()
        print(f"   Creation successful!")
        print(f"   commission: {default_comminfo.get_param('commission')}")
        print(f"   margin: {default_comminfo.get_param('margin')}")
        print(f"   mult: {default_comminfo.get_param('mult')}")
        print(f"   stocklike: {default_comminfo.get_param('stocklike')}")
        print(f"   _stocklike: {default_comminfo._stocklike}")
        print(f"   _commtype: {default_comminfo._commtype}")
        print(f"   property stocklike: {default_comminfo.stocklike}")
        print(f"   property margin: {default_comminfo.margin}")

    except Exception as e:
        print(f"   Creation failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_parameter_setting_details()
