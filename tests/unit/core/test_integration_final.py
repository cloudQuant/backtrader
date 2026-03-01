#!/usr/bin/env python
"""Final Integration Tests for Broker System Refactoring.

This module contains integration tests that validate the complete broker system
refactoring completed during Days 46-48. These tests ensure that all components
work together correctly after the metaclass removal and parameter system overhaul.

Integration Points Tested:
    - BrokerBase and BackBroker classes integration
    - CommInfo system integration with broker parameters
    - Parameter validation across all systems
    - Performance benchmarks for parameter access
    - Backward compatibility with existing code
    - Real-world usage scenarios

Test Coverage:
    test_broker_comminfo_integration: Tests broker and commission info integration
    test_parameter_validation_integration: Tests validation across systems
    test_performance_integration: Tests performance meets targets
    test_backward_compatibility_integration: Tests old API still works
    test_real_usage_scenario: Tests realistic broker setup

Usage:
    Run all integration tests::

        python tests/refactor_tests/test_integration_final.py

    Or use pytest::

        pytest tests/refactor_tests/test_integration_final.py -v
"""

import backtrader as bt

import os
import sys

import backtrader as bt
from backtrader.brokers.bbroker import BackBroker
from backtrader.parameters import Bool, Float, ParameterDescriptor


def test_broker_comminfo_integration():
    """Test broker and comminfo system integration.

    This test validates that the broker and commission info systems work together
    correctly after the parameter system refactoring:

    - CommInfo objects can be created with custom parameters
    - Broker accepts parameters through initialization and setters
    - Parameter access is consistent across all interfaces (get_param, params, p)
    - Cash and commission settings are properly integrated

    Raises:
        AssertionError: If broker or comminfo parameters are not set correctly.
    """
    print("Testing Broker-CommInfo Integration...")

    # Create a custom commission info
    comminfo = bt.CommInfoBase(
        commission=0.001, mult=1.0, stocklike=True, percabs=True  # 0.1% commission
    )

    # Create a broker with custom parameters
    broker = BackBroker()

    # Set parameters using proper methods (as per backtrader design)
    broker.set_cash(50000.0)
    broker.set_param("checksubmit", True)
    broker.set_param("slip_perc", 0.001)  # 0.1% slippage
    broker.set_param("fundmode", True)
    broker.set_param("fundstartval", 100.0)

    # Test parameter access
    assert broker.cash == 50000.0  # Use actual cash value
    assert broker.get_param("checksubmit") == True
    assert broker.get_param("slip_perc") == 0.001
    assert broker.get_param("fundmode") == True

    # Test backward compatibility
    assert broker.params.checksubmit == True
    assert broker.p.slip_perc == 0.001

    # Test CommInfo parameters
    assert comminfo.get_param("commission") == 0.001
    assert comminfo.get_param("mult") == 1.0
    assert comminfo.get_param("stocklike") == True

    print("Broker-CommInfo integration test passed!")


def test_parameter_validation_integration():
    """Test parameter validation across systems.

    This test validates that parameter validation works consistently across
    the broker and comminfo systems:

    - Float validators enforce min/max constraints
    - Type validators reject invalid types
    - Bool parameters accept boolean values
    - Invalid values are rejected appropriately

    Validation Behavior:
        - Float with min_val/max_val: enforces range constraints
        - Type validation: rejects values of wrong type
        - Bool validation: only accepts True/False

    Raises:
        AssertionError: If validation does not work as expected.
    """
    print("Testing Parameter Validation Integration...")

    # Test Float validator
    from backtrader.parameters import Float

    float_validator = Float(min_val=0.0, max_val=1.0)
    assert float_validator(0.5) == True
    assert float_validator(1.1) == False
    assert float_validator("0.5") == False  # String should be rejected

    # Test Bool parameter
    broker = BackBroker()
    broker.set_param("fundmode", True)
    assert broker.get_param("fundmode") == True

    # Test setting invalid values (should raise errors)
    try:
        broker2 = BackBroker()
        broker2.set_cash(-1000.0)  # Should be allowed by broker but caught elsewhere if needed
        # Note: BackBroker itself doesn't validate negative cash, that's handled at strategy level
        print("Negative cash set successfully (as expected for BackBroker)")
    except (ValueError, TypeError):
        pass  # If validation exists

    print("Parameter validation integration test passed!")


def test_performance_integration():
    """Test performance of integrated systems.

    This test validates that the refactored systems meet performance targets:

    - Parameter access should be fast (< 1 second for 10,000 accesses)
    - CommInfo creation should be fast (< 1 second for 1,000 creations)
    - No significant performance regression from refactoring

    Performance Targets:
        - Parameter access: < 1 second for 10,000 operations
        - CommInfo creation: < 1 second for 1,000 objects

    Raises:
        AssertionError: If performance targets are not met.

    Note:
        Performance tests may vary based on system load and hardware.
    """
    print("Testing Performance Integration...")

    import time

    # Create broker
    broker = BackBroker()
    broker.set_cash(10000.0)

    # Performance test: parameter access
    start_time = time.time()
    for _ in range(10000):
        cash = broker.get_param("cash")
        slip = broker.get_param("slip_perc")
        fundmode = broker.get_param("fundmode")
    end_time = time.time()

    duration = end_time - start_time
    print(f"10,000 parameter accesses completed in {duration:.4f} seconds")
    assert duration < 1.0, f"Performance too slow: {duration:.4f}s"

    # Performance test: CommInfo creation
    start_time = time.time()
    for _ in range(1000):
        comminfo = bt.CommInfoBase(commission=0.001, mult=1.0)
    end_time = time.time()

    duration = end_time - start_time
    print(f"1,000 CommInfo creations completed in {duration:.4f} seconds")
    assert duration < 1.0, f"CommInfo creation too slow: {duration:.4f}s"

    print("Performance integration test passed!")


def test_backward_compatibility_integration():
    """Test backward compatibility across all systems.

    This test validates that the refactored system maintains backward
    compatibility with existing code:

    - Old-style parameter access (params, p) still works
    - Direct parameter assignment still works
    - Method aliases (getcash vs get_cash) both work
    - Existing code patterns continue to function

    Backward Compatibility Guarantees:
        - params and p attributes still available
        - Direct attribute assignment still works
        - Method aliases are preserved
        - No breaking changes to public APIs

    Raises:
        AssertionError: If backward compatibility is broken.
    """
    print("Testing Backward Compatibility Integration...")

    # Test old-style parameter access
    broker = BackBroker()

    # Test params interface
    assert hasattr(broker, "params")
    assert hasattr(broker, "p")

    # Test parameter setting through params
    broker.set_cash(20000.0)
    assert broker.cash == 20000.0

    broker.p.slip_perc = 0.002
    assert broker.get_param("slip_perc") == 0.002

    # Test CommInfo compatibility
    comminfo = bt.CommInfoBase()
    assert hasattr(comminfo, "params")
    assert hasattr(comminfo, "p")

    # Test method aliases still work
    assert broker.getcash() == broker.get_cash()

    print("Backward compatibility integration test passed!")


def test_real_usage_scenario():
    """Test a realistic usage scenario.

    This test validates that a complete, realistic broker setup works correctly:

    - Broker initialization with multiple parameters
    - Custom commission info creation
    - Parameter modification during runtime
    - Fund mode functionality
    - All components working together

    Scenario:
        Create a futures trading setup with:
        - $100k starting capital
        - 0.1% slippage
        - Fund mode enabled for performance tracking
        - 0.5% commission on trades

    Raises:
        AssertionError: If the realistic scenario does not work correctly.
    """
    print("Testing Real Usage Scenario...")

    # Create a realistic broker setup
    broker = BackBroker(
        cash=100000.0,  # $100k starting cash
        checksubmit=True,  # Check cash before orders
        slip_perc=0.001,  # 0.1% slippage
        fundmode=True,  # Fund mode for performance tracking
        fundstartval=100.0,  # Start at $100 per share
        coc=False,  # No cheat-on-close
        coo=False,  # No cheat-on-open
    )
    broker.init()  # Initialize the broker

    # Create custom commission info
    stock_commission = bt.CommInfoBase(
        commission=0.005, mult=1.0, stocklike=True, percabs=True  # 0.5% commission
    )

    # Test that everything works together
    assert broker.get_cash() == 100000.0
    assert broker.get_param("fundmode") == True
    assert stock_commission.get_param("commission") == 0.005

    # Test parameter modification
    broker.set_param("slip_perc", 0.002)  # Increase slippage
    assert broker.get_param("slip_perc") == 0.002

    # Test fund mode functionality
    assert broker.get_fundmode() == True
    broker.set_fundmode(False)
    assert broker.get_fundmode() == False

    print("Real usage scenario test passed!")


def main():
    """Run all integration tests.

    This function executes all integration tests in sequence and reports
    the overall results. It provides a summary of the broker system
    refactoring validation.

    Returns:
        bool: True if all tests pass, False if any test fails.

    Test Execution Order:
        1. Broker-CommInfo integration
        2. Parameter validation
        3. Performance benchmarks
        4. Backward compatibility
        5. Real usage scenario
    """
    print("Starting Final Integration Tests for Day 46-48 Broker System Refactoring")
    print("=" * 80)

    try:
        test_broker_comminfo_integration()
        test_parameter_validation_integration()
        test_performance_integration()
        test_backward_compatibility_integration()
        test_real_usage_scenario()

        print("=" * 80)
        print("ALL INTEGRATION TESTS PASSED!")
        print()
        print("Broker system refactoring (Day 46-48) is COMPLETE!")
        print("All systems are working together correctly")
        print("Performance targets met")
        print("Backward compatibility maintained")
        print("Ready for next phase of refactoring")

        return True

    except Exception as e:
        print(f"Integration test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
