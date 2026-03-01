#!/usr/bin/env python
"""Parameter Manager Integration Tests.

This module provides tests to validate and inspect the parameter manager
implementation in the backtrader framework. It serves as both a test suite
and a diagnostic tool for understanding how parameters are managed.

Test Coverage:
    - Class-level parameter descriptors
    - Parameter initialization and defaults
    - Parameter access methods (get_param, property access)
    - Parameter modification (set_param)
    - Internal parameter manager state

Usage:
    Run as a standalone script to inspect parameter manager behavior::

        python tests/refactor_tests/test_param_manager.py

    Use with pytest for test execution::

        pytest tests/refactor_tests/test_param_manager.py -v

Example Output:
        The script prints detailed information about parameter descriptors,
        values, and defaults to help diagnose parameter manager issues.
"""

import backtrader as bt
import os
import sys

# Add project root to path for imports
sys.path.insert(0, ".")


def test_param_manager():
    """Test whether the parameter manager works correctly.

    This test function verifies the functionality of the parameter manager
    by checking class-level parameter descriptors, creating a CommInfo object
    with custom parameters, and testing parameter access methods.

    The test performs the following validations:
        1. Class-level descriptors are properly registered
        2. Descriptors contain correct default values and types
        3. Parameter manager initializes correctly for new objects
        4. Values and defaults are stored separately in the manager
        5. Parameter access works through both get_param() and property access
        6. Parameter modification updates both manager and property views

    Test Process:
        1. Inspect class-level parameter descriptors on bt.CommInfoBase
        2. Create a CommInfoBase instance with custom margin parameter
        3. Print internal parameter manager state for diagnosis
        4. Verify parameter access through multiple methods
        5. Test parameter modification and verify consistency

    Note:
        This function is primarily diagnostic. It prints detailed information
        about the parameter manager state rather than making assertions.

    Example:
        >>> test_param_manager()
        === Testing Parameter Manager ===
        bt.CommInfoBase class descriptors: ['margin', 'commission', ...]
        margin: default=1000.0, type=<class 'float'>
        ...
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

    # Inspect internal parameter manager state
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

    # Test parameter access methods
    print(f"Directly call get_param('margin'): {comminfo.get_param('margin')}")
    print(f"Access margin through property: {comminfo.margin}")

    # Test parameter modification
    print(f"\nManually setting margin to 2000.0...")
    comminfo.set_param("margin", 2000.0)
    print(f"After setting, get_param('margin'): {comminfo.get_param('margin')}")
    print(f"After setting, property margin: {comminfo.margin}")


if __name__ == "__main__":
    test_param_manager()
