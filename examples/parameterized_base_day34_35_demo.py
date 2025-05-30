#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Enhanced ParameterizedBase Demonstration (Day 34-35)

This example demonstrates the enhanced ParameterizedBase functionality implemented
for Day 34-35 of the backtrader metaprogramming removal project.

Day 34-35 Enhancements Demonstrated:
- Temporary MetaParams integration for seamless migration
- Enhanced error handling and validation
- Improved backward compatibility interfaces
- Parameter inheritance from MetaParams-based classes
- Advanced parameter validation and type checking
- Parameter copying and management utilities
"""

import sys
import os

# Add backtrader to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backtrader.parameters import (
    ParameterDescriptor, ParameterManager, ParameterizedBase, HybridParameterMeta,
    Int, Float, OneOf, String, MetaParamsBridge, ParameterValidationError,
    ParameterAccessError, validate_parameter_compatibility
)


def demonstrate_enhanced_parameter_validation():
    """Demonstrate enhanced parameter validation with detailed error reporting."""
    print("=== Enhanced Parameter Validation Demo ===")
    
    # Custom validator for demonstration
    def positive_even_validator(value):
        """Value must be positive and even"""
        return isinstance(value, int) and value > 0 and value % 2 == 0
    
    class EnhancedValidationExample(ParameterizedBase):
        # Required parameter
        required_name = ParameterDescriptor(
            required=True,
            type_=str,
            doc="Name is required and must be a string"
        )
        
        # Range-validated parameter
        percentage = ParameterDescriptor(
            default=50,
            type_=float,
            validator=Float(min_val=0.0, max_val=100.0),
            doc="Percentage between 0 and 100"
        )
        
        # Custom validated parameter
        even_number = ParameterDescriptor(
            default=2,
            type_=int,
            validator=positive_even_validator,
            doc="Must be a positive even number"
        )
        
        # Choice-restricted parameter
        mode = ParameterDescriptor(
            default='fast',
            type_=str,
            validator=OneOf('fast', 'slow', 'auto'),
            doc="Processing mode"
        )
    
    print("Creating object with valid parameters...")
    try:
        obj = EnhancedValidationExample(
            required_name="Test Object",
            percentage=75.5,
            even_number=8,
            mode='fast'
        )
        print("✓ Object created successfully")
        print(f"  Name: {obj.get_param('required_name')}")
        print(f"  Percentage: {obj.get_param('percentage')}")
        print(f"  Even number: {obj.get_param('even_number')}")
        print(f"  Mode: {obj.get_param('mode')}")
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
    
    print("\nTrying to create object with missing required parameter...")
    try:
        bad_obj = EnhancedValidationExample(percentage=25.0)
    except ValueError as e:
        print(f"✓ Correctly caught validation error: {e}")
    
    print("\nTrying to create object with invalid range...")
    try:
        bad_obj = EnhancedValidationExample(
            required_name="Test",
            percentage=150.0  # Invalid: > 100
        )
    except ValueError as e:
        print(f"✓ Correctly caught range validation error")
    
    print("\nTrying to create object with invalid custom validation...")
    try:
        bad_obj = EnhancedValidationExample(
            required_name="Test",
            even_number=7  # Invalid: odd number
        )
    except ValueError as e:
        print(f"✓ Correctly caught custom validation error")
    
    print()


def demonstrate_legacy_params_compatibility():
    """Demonstrate compatibility with legacy params tuple syntax."""
    print("=== Legacy Params Compatibility Demo ===")
    
    # Class using legacy params tuple syntax
    class LegacyStyleClass(ParameterizedBase):
        params = (
            ('period', 14),
            ('multiplier', 2.0),
            ('signal_type', 'ema'),
            ('enabled', True)
        )
    
    print("Legacy-style parameter definition:")
    print("  params = (('period', 14), ('multiplier', 2.0), ('signal_type', 'ema'), ('enabled', True))")
    
    # Create object with legacy-style parameters
    obj = LegacyStyleClass(period=20, multiplier=1.5)
    
    print(f"\nCreated object with modified parameters:")
    print(f"  Period: {obj.get_param('period')} (modified from default 14)")
    print(f"  Multiplier: {obj.get_param('multiplier')} (modified from default 2.0)")
    print(f"  Signal type: {obj.get_param('signal_type')} (default)")
    print(f"  Enabled: {obj.get_param('enabled')} (default)")
    
    # Show parameter info
    param_info = obj.get_param_info()
    print(f"\nParameter information:")
    for name, info in param_info.items():
        print(f"  {name}: {info['current_value']} (default: {info['default']}, modified: {not info['is_default']})")
    
    print()


def demonstrate_mixed_parameter_styles():
    """Demonstrate mixing legacy and modern parameter styles."""
    print("=== Mixed Parameter Styles Demo ===")
    
    class MixedStyleClass(ParameterizedBase):
        # Modern descriptor-based parameters
        advanced_param = ParameterDescriptor(
            default=100,
            type_=int,
            validator=Int(min_val=1, max_val=1000),
            doc="Advanced parameter with validation"
        )
        
        string_param = ParameterDescriptor(
            default="default_value",
            type_=str,
            validator=String(min_length=3, max_length=20),
            doc="String with length validation"
        )
        
        # Legacy params tuple
        params = (
            ('basic_param', 42),
            ('flag_param', False),
            ('name_param', 'legacy_style')
        )
    
    print("Class with mixed parameter styles:")
    print("  - Modern descriptors with validation")
    print("  - Legacy params tuple")
    
    obj = MixedStyleClass(
        advanced_param=500,
        string_param="custom",
        basic_param=100,
        flag_param=True
    )
    
    print(f"\nParameter values:")
    for name, value in obj._param_manager.items():
        descriptor = obj._param_manager._descriptors.get(name)
        if descriptor and descriptor.doc:
            print(f"  {name}: {value} ({descriptor.doc})")
        else:
            print(f"  {name}: {value} (legacy parameter)")
    
    print()


def demonstrate_enhanced_error_handling():
    """Demonstrate enhanced error handling with detailed context."""
    print("=== Enhanced Error Handling Demo ===")
    
    class ErrorHandlingExample(ParameterizedBase):
        valid_param = ParameterDescriptor(default=10, type_=int)
        range_param = ParameterDescriptor(default=50, validator=Int(min_val=0, max_val=100))
    
    obj = ErrorHandlingExample()
    
    print("Testing parameter access errors...")
    
    # Test accessing non-existent parameter
    try:
        value = obj.get_param('nonexistent_param')
    except AttributeError as e:
        print(f"✓ Detailed access error: {e}")
    
    # Test setting non-existent parameter
    try:
        obj.set_param('another_nonexistent', 123)
    except AttributeError as e:
        print(f"✓ Detailed setting error: {e}")
    
    # Test setting invalid value with validation
    try:
        obj.set_param('range_param', 150)  # Out of range
    except ValueError as e:
        print(f"✓ Detailed validation error: {e}")
    
    # Test type conversion error
    try:
        obj.set_param('valid_param', "not_a_number")
    except (TypeError, ValueError) as e:
        print(f"✓ Detailed type/validation error: {e}")
    
    print()


def demonstrate_parameter_management_utilities():
    """Demonstrate advanced parameter management utilities."""
    print("=== Parameter Management Utilities Demo ===")
    
    class UtilitiesExample(ParameterizedBase):
        param1 = ParameterDescriptor(default=10)
        param2 = ParameterDescriptor(default=20)
        param3 = ParameterDescriptor(default=30)
        param4 = ParameterDescriptor(default=40)
    
    # Create objects
    source = UtilitiesExample(param1=100, param2=200, param3=300)
    target = UtilitiesExample(param1=15, param4=50)
    
    print("Source object parameters:")
    for name, value in source.get_modified_params().items():
        print(f"  {name}: {value}")
    
    print("Target object parameters (before copying):")
    for name, value in target.get_modified_params().items():
        print(f"  {name}: {value}")
    
    # Copy specific parameters
    print("\nCopying param1 and param3 from source to target...")
    target.copy_params_from(source, param_names=['param1', 'param3'])
    
    print("Target object parameters (after copying):")
    for name, value in target.get_modified_params().items():
        print(f"  {name}: {value}")
    
    # Reset parameters
    print("\nResetting param1 to default...")
    target.reset_param('param1')
    
    print("Target object parameters (after reset):")
    for name, value in target.get_modified_params().items():
        print(f"  {name}: {value}")
    
    # Reset all parameters
    print("\nResetting all parameters to defaults...")
    target.reset_all_params()
    
    modified = target.get_modified_params()
    if modified:
        print("Modified parameters after reset:")
        for name, value in modified.items():
            print(f"  {name}: {value}")
    else:
        print("✓ All parameters reset to defaults")
    
    print()


def demonstrate_parameter_inheritance():
    """Demonstrate parameter inheritance through class hierarchy."""
    print("=== Parameter Inheritance Demo ===")
    
    class BaseIndicator(ParameterizedBase):
        period = ParameterDescriptor(default=14, type_=int, validator=Int(min_val=1))
        source = ParameterDescriptor(default='close', validator=OneOf('open', 'high', 'low', 'close'))
    
    class MovingAverage(BaseIndicator):
        ma_type = ParameterDescriptor(default='simple', validator=OneOf('simple', 'exponential', 'weighted'))
        
    class MACD(MovingAverage):
        fast_period = ParameterDescriptor(default=12, type_=int, validator=Int(min_val=1))
        slow_period = ParameterDescriptor(default=26, type_=int, validator=Int(min_val=1))
        signal_period = ParameterDescriptor(default=9, type_=int, validator=Int(min_val=1))
    
    print("Class hierarchy: BaseIndicator -> MovingAverage -> MACD")
    
    # Create MACD instance
    macd = MACD(
        period=21,           # From BaseIndicator
        ma_type='exponential', # From MovingAverage
        fast_period=10,      # From MACD
        slow_period=20       # From MACD
        # signal_period uses default
        # source uses default
    )
    
    print(f"\nMACD instance parameters:")
    param_info = macd.get_param_info()
    for name, info in param_info.items():
        status = "modified" if not info['is_default'] else "default"
        print(f"  {name}: {info['current_value']} ({status})")
    
    # Show enhanced string representation
    print(f"\nString representation: {repr(macd)}")
    
    print()


def demonstrate_metaparams_bridge():
    """Demonstrate MetaParams bridge utilities."""
    print("=== MetaParams Bridge Demo ===")
    
    # Simulate converting legacy params tuple
    legacy_params = (
        ('lookback_period', 20),
        ('threshold', 0.02),
        ('signal_mode', 'crossover'),
        ('enabled', True)
    )
    
    print("Converting legacy params tuple:")
    print(f"  {legacy_params}")
    
    descriptors = MetaParamsBridge.convert_legacy_params_tuple(legacy_params)
    
    print(f"\nConverted to {len(descriptors)} parameter descriptors:")
    for name, desc in descriptors.items():
        type_name = desc.type_.__name__ if desc.type_ else "Any"
        print(f"  {name}: default={desc.default}, type={type_name}")
    
    # Create a class using the converted descriptors
    class ConvertedClass(ParameterizedBase):
        pass
    
    # Add descriptors to the class
    for name, desc in descriptors.items():
        setattr(ConvertedClass, name, desc)
    
    # Update parameter descriptors manually (normally done by metaclass)
    ConvertedClass._parameter_descriptors = descriptors
    
    obj = ConvertedClass(lookback_period=30, threshold=0.05)
    print(f"\nCreated object from converted descriptors:")
    print(f"  Lookback period: {obj.get_param('lookback_period')}")
    print(f"  Threshold: {obj.get_param('threshold')}")
    print(f"  Signal mode: {obj.get_param('signal_mode')}")
    print(f"  Enabled: {obj.get_param('enabled')}")
    
    print()


def demonstrate_advanced_validation_scenarios():
    """Demonstrate advanced validation scenarios and error recovery."""
    print("=== Advanced Validation Scenarios Demo ===")
    
    def fibonacci_validator(value):
        """Check if value is a Fibonacci number"""
        if not isinstance(value, int) or value < 0:
            return False
        
        # Check if value is a Fibonacci number
        a, b = 0, 1
        while b < value:
            a, b = b, a + b
        return b == value
    
    class AdvancedValidationExample(ParameterizedBase):
        # Complex validator
        fib_number = ParameterDescriptor(
            default=1,
            type_=int,
            validator=fibonacci_validator,
            doc="Must be a Fibonacci number"
        )
        
        # Multiple constraints
        constrained_float = ParameterDescriptor(
            default=1.0,
            type_=float,
            validator=lambda x: isinstance(x, (int, float)) and 0.1 <= x <= 10.0 and x != 5.0,
            doc="Float between 0.1 and 10.0, but not exactly 5.0"
        )
    
    print("Testing Fibonacci number validation...")
    
    # Valid Fibonacci numbers
    for fib_val in [1, 2, 3, 5, 8, 13, 21]:
        try:
            obj = AdvancedValidationExample(fib_number=fib_val)
            print(f"  ✓ {fib_val} is a valid Fibonacci number")
        except ValueError:
            print(f"  ✗ {fib_val} validation failed unexpectedly")
    
    # Invalid numbers
    for invalid_val in [4, 6, 7, 9, 10]:
        try:
            obj = AdvancedValidationExample(fib_number=invalid_val)
            print(f"  ✗ {invalid_val} should have failed validation")
        except ValueError:
            print(f"  ✓ {invalid_val} correctly rejected (not Fibonacci)")
    
    print("\nTesting constrained float validation...")
    
    # Valid values
    for val in [0.1, 1.0, 2.5, 9.9]:
        try:
            obj = AdvancedValidationExample(constrained_float=val)
            print(f"  ✓ {val} is valid")
        except ValueError:
            print(f"  ✗ {val} validation failed unexpectedly")
    
    # Invalid values
    for val in [0.05, 5.0, 15.0]:
        try:
            obj = AdvancedValidationExample(constrained_float=val)
            print(f"  ✗ {val} should have failed validation")
        except ValueError:
            print(f"  ✓ {val} correctly rejected")
    
    print()


if __name__ == '__main__':
    print("Enhanced ParameterizedBase Demonstration (Day 34-35)")
    print("=" * 60)
    print()
    
    demonstrate_enhanced_parameter_validation()
    demonstrate_legacy_params_compatibility()
    demonstrate_mixed_parameter_styles()
    demonstrate_enhanced_error_handling()
    demonstrate_parameter_management_utilities()
    demonstrate_parameter_inheritance()
    demonstrate_metaparams_bridge()
    demonstrate_advanced_validation_scenarios()
    
    print("=" * 60)
    print("✓ All Day 34-35 enhancements demonstrated successfully!")
    print()
    print("Summary of Day 34-35 ParameterizedBase enhancements:")
    print("  ✓ Temporary MetaParams integration for seamless migration")
    print("  ✓ Enhanced error handling with detailed context information")
    print("  ✓ Improved backward compatibility with legacy params tuples")
    print("  ✓ Advanced parameter validation and type checking")
    print("  ✓ Parameter management utilities (copy, reset, tracking)")
    print("  ✓ Comprehensive parameter inheritance through class hierarchy")
    print("  ✓ MetaParams bridge utilities for migration assistance")
    print("  ✓ Custom validation scenarios and error recovery")
    print("  ✓ Enhanced string representation and debugging support") 