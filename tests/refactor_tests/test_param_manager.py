#!/usr/bin/env python

import backtrader as bt
import os
import sys

sys.path.insert(0, ".")



def test_param_manager():
    """Test whether the parameter manager works correctly.

    This test function verifies the functionality of the parameter manager
    by checking class-level parameter descriptors, creating a CommInfo object
    with custom parameters, and testing parameter access methods.
    """
    print("=== Testing Parameter Manager ===")

    # Check class-level parameter descriptors
    print(f"bt.CommInfoBase class descriptors: {list(bt.CommInfoBase._parameter_descriptors.keys())}")

    # Check detailed information for each descriptor
    for name, descriptor in bt.CommInfoBase._parameter_descriptors.items():
        print(f"  {name}: default={descriptor.default}, type={descriptor.type_}")

    # Create CommInfo object and observe parameter setting process
    print("\nCreating CommInfo object: bt.CommInfoBase(margin=1000.0)")

    comminfo = bt.CommInfoBase(margin=1000.0)

    print(f"Descriptors in parameter manager: {list(comminfo._param_manager._descriptors.keys())}")
    print(f"Values in parameter manager: {comminfo._param_manager._values}")
    print(f"Defaults in parameter manager: {comminfo._param_manager._defaults}")

    # Test direct access to class descriptors
    print(f"\nDirectly access margin descriptor from class: {hasattr(bt.CommInfoBase, 'margin')}")
    if hasattr(bt.CommInfoBase, "margin"):
        print(f"Class margin descriptor: {bt.CommInfoBase.margin}")
        print(f"Margin descriptor type: {type(bt.CommInfoBase.margin)}")

    print(f"Directly access stocklike descriptor from class: {hasattr(bt.CommInfoBase, 'stocklike')}")
    if hasattr(bt.CommInfoBase, "stocklike"):
        print(f"Class stocklike descriptor: {bt.CommInfoBase.stocklike}")
        print(f"Stocklike descriptor type: {type(bt.CommInfoBase.stocklike)}")

    print(f"Directly call get_param('margin'): {comminfo.get_param('margin')}")
    print(f"Access margin through property: {comminfo.margin}")

    # Manually set to verify it works
    print(f"\nManually setting margin to 2000.0...")
    comminfo.set_param("margin", 2000.0)
    print(f"After setting, get_param('margin'): {comminfo.get_param('margin')}")
    print(f"After setting, property margin: {comminfo.margin}")


if __name__ == "__main__":
    test_param_manager()
