#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Parameter System Demonstration

This example demonstrates the new ParameterDescriptor system implemented
for Day 29-31 of the backtrader metaprogramming removal project.

The new system provides:
- Type checking and automatic conversion
- Value validation
- Python 3.6+ __set_name__ support
- Backward compatibility with existing parameter interface
"""

import sys
import os

# Add backtrader to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backtrader.parameters import (
    ParameterDescriptor, ParameterizedBase,
    Int, Float, OneOf, String
)


# Example 1: Basic Parameter Usage
class SimpleStrategy(ParameterizedBase):
    """A simple strategy demonstrating basic parameter usage."""
    
    # Basic parameters with default values and type checking
    period = ParameterDescriptor(default=14, type_=int, doc="Moving average period")
    factor = ParameterDescriptor(default=1.0, type_=float, doc="Risk factor")
    name = ParameterDescriptor(default="SimpleStrategy", type_=str, doc="Strategy name")


# Example 2: Advanced Parameter Validation
class AdvancedStrategy(ParameterizedBase):
    """Strategy with advanced parameter validation."""
    
    # Parameter with range validation
    period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=5, max_val=200),
        doc="Period must be between 5 and 200"
    )
    
    # Parameter with choice validation
    signal_type = ParameterDescriptor(
        default="crossover",
        validator=OneOf("crossover", "divergence", "momentum"),
        doc="Type of signal to use"
    )
    
    # Parameter with float range validation
    risk_level = ParameterDescriptor(
        default=0.02,
        type_=float,
        validator=Float(min_val=0.001, max_val=0.1),
        doc="Risk level between 0.1% and 10%"
    )
    
    # String parameter with length validation
    description = ParameterDescriptor(
        default="Advanced trading strategy",
        validator=String(min_length=5, max_length=100),
        doc="Strategy description (5-100 characters)"
    )


# Example 3: Parameter Inheritance
class BaseIndicator(ParameterizedBase):
    """Base indicator with common parameters."""
    
    period = ParameterDescriptor(default=14, type_=int, doc="Calculation period")
    plot = ParameterDescriptor(default=True, type_=bool, doc="Whether to plot")


class MovingAverage(BaseIndicator):
    """Moving average indicator inheriting from base."""
    
    # Inherits 'period' and 'plot' from BaseIndicator
    # Adds its own parameters
    ma_type = ParameterDescriptor(
        default="simple",
        validator=OneOf("simple", "exponential", "weighted"),
        doc="Type of moving average"
    )


class MACD(BaseIndicator):
    """MACD indicator with multiple periods."""
    
    # Override the base period with different default
    period = ParameterDescriptor(default=12, type_=int, doc="Fast period")
    
    # Add additional periods
    slow_period = ParameterDescriptor(default=26, type_=int, doc="Slow period")
    signal_period = ParameterDescriptor(default=9, type_=int, doc="Signal period")


# Example 4: Custom Validator
def positive_odd_number(value):
    """Custom validator for positive odd numbers."""
    return isinstance(value, int) and value > 0 and value % 2 == 1


class CustomValidatorExample(ParameterizedBase):
    """Example using a custom validator."""
    
    odd_period = ParameterDescriptor(
        default=21,
        type_=int,
        validator=positive_odd_number,
        doc="Period must be a positive odd number"
    )


def demonstrate_basic_usage():
    """Demonstrate basic parameter usage."""
    print("=== Basic Parameter Usage ===")
    
    # Create strategy with default parameters
    strategy1 = SimpleStrategy()
    print(f"Default parameters: period={strategy1.period}, factor={strategy1.factor}, name='{strategy1.name}'")
    
    # Create strategy with custom parameters
    strategy2 = SimpleStrategy(period=21, factor=2.0, name="Custom Strategy")
    print(f"Custom parameters: period={strategy2.period}, factor={strategy2.factor}, name='{strategy2.name}'")
    
    # Demonstrate parameter access methods
    print(f"Access via obj.period: {strategy2.period}")
    print(f"Access via obj.params.period: {strategy2.params.period}")
    print(f"Access via obj.p.period: {strategy2.p.period}")
    
    # Demonstrate type conversion
    strategy2.period = "30"  # String converted to int
    print(f"After string assignment: period={strategy2.period} (type: {type(strategy2.period)})")
    
    print()


def demonstrate_validation():
    """Demonstrate parameter validation."""
    print("=== Parameter Validation ===")
    
    # Valid parameters
    strategy = AdvancedStrategy(
        period=50,
        signal_type="momentum",
        risk_level=0.05,
        description="A well-tested strategy"
    )
    print("✓ Created strategy with valid parameters")
    
    # Demonstrate validation errors
    try:
        strategy.period = 300  # Too large
    except ValueError as e:
        print(f"✗ Period validation error: {e}")
    
    try:
        strategy.signal_type = "invalid_type"  # Not in choices
    except ValueError as e:
        print(f"✗ Signal type validation error: {e}")
    
    try:
        strategy.risk_level = 0.5  # Too large
    except ValueError as e:
        print(f"✗ Risk level validation error: {e}")
    
    try:
        strategy.description = "Too short"  # Length validation
    except ValueError as e:
        print(f"✗ Description validation error: {e}")
    
    print()


def demonstrate_inheritance():
    """Demonstrate parameter inheritance."""
    print("=== Parameter Inheritance ===")
    
    # Base indicator
    base = BaseIndicator(period=20, plot=False)
    print(f"Base indicator: period={base.period}, plot={base.plot}")
    
    # Moving average inherits from base
    ma = MovingAverage(period=50, plot=True, ma_type="exponential")
    print(f"Moving Average: period={ma.period}, plot={ma.plot}, ma_type={ma.ma_type}")
    
    # MACD with multiple periods
    macd = MACD(period=15, slow_period=30, signal_period=12)
    print(f"MACD: period={macd.period}, slow_period={macd.slow_period}, signal_period={macd.signal_period}")
    
    print()


def demonstrate_introspection():
    """Demonstrate parameter introspection capabilities."""
    print("=== Parameter Introspection ===")
    
    strategy = AdvancedStrategy()
    
    # Get parameter information
    param_info = strategy.get_param_info()
    
    print("Parameter Information:")
    for name, info in param_info.items():
        print(f"  {name}:")
        print(f"    Type: {info['type']}")
        print(f"    Default: {info['default']}")
        print(f"    Has Validator: {info['has_validator']}")
        print(f"    Documentation: {info['doc']}")
        print()
    
    # Validate all parameters
    errors = strategy.validate_params()
    if errors:
        print("Validation errors:")
        for error in errors:
            print(f"  ✗ {error}")
    else:
        print("✓ All parameters are valid")
    
    print()


def demonstrate_custom_validators():
    """Demonstrate custom validator usage."""
    print("=== Custom Validators ===")
    
    # Valid odd number
    example = CustomValidatorExample(odd_period=15)
    print(f"✓ Valid odd period: {example.odd_period}")
    
    # Test validation errors
    try:
        example.odd_period = 16  # Even number
    except ValueError as e:
        print(f"✗ Even number error: {e}")
    
    try:
        example.odd_period = -5  # Negative number
    except ValueError as e:
        print(f"✗ Negative number error: {e}")
    
    print()


def demonstrate_backward_compatibility():
    """Demonstrate backward compatibility with old parameter interface."""
    print("=== Backward Compatibility ===")
    
    strategy = AdvancedStrategy(period=30, risk_level=0.03)
    
    # Old-style parameter access still works
    print("Old-style parameter access methods:")
    
    # Get items like old system
    items = list(strategy.params._getitems())
    print(f"_getitems(): {dict(items)}")
    
    # Get keys like old system
    keys = strategy.params._getkeys()
    print(f"_getkeys(): {keys}")
    
    # Get values like old system
    values = strategy.params._getvalues()
    print(f"_getvalues(): {values}")
    
    # Dictionary-style access
    print(f"params['period']: {strategy.params['period']}")
    strategy.params['period'] = 40
    print(f"After setting params['period'] = 40: {strategy.period}")
    
    print()


if __name__ == '__main__':
    print("ParameterDescriptor System Demonstration")
    print("=" * 50)
    print()
    
    demonstrate_basic_usage()
    demonstrate_validation()
    demonstrate_inheritance()
    demonstrate_introspection()
    demonstrate_custom_validators()
    demonstrate_backward_compatibility()
    
    print("=" * 50)
    print("✓ All demonstrations completed successfully!")
    print()
    print("Summary of features demonstrated:")
    print("  ✓ Basic descriptor functionality")
    print("  ✓ Type checking and automatic conversion")
    print("  ✓ Value validation with built-in validators")
    print("  ✓ Python 3.6+ __set_name__ support")
    print("  ✓ Parameter inheritance between classes")
    print("  ✓ Parameter introspection capabilities")
    print("  ✓ Custom validator functions")
    print("  ✓ Backward compatibility with old parameter interface") 