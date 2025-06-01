"""
Comprehensive Examples for Backtrader's New Parameter System

This file demonstrates all the features and capabilities of the new descriptor-based
parameter system that replaces the old metaclass-based approach.

Examples include:
1. Basic parameter usage
2. Type validation and conversion
3. Custom validators
4. Parameter groups and organization
5. Change callbacks and history
6. Advanced features like lazy defaults
7. Migration patterns
8. Performance demonstrations
"""

import time
import sys
import os

# Add backtrader to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backtrader.parameters import (
    ParameterizedBase, ParameterDescriptor, ParameterManager,
    Int, Float, Bool, String, OneOf,
    FloatParam, BoolParam, StringParam,
    MetaParamsBridge, validate_parameter_compatibility,
    ParameterValidationError, ParameterAccessError
)


# =============================================================================
# Example 1: Basic Parameter Usage
# =============================================================================

class BasicIndicator(ParameterizedBase):
    """Basic example showing simple parameter definitions."""
    
    period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=1, max_val=500),
        doc="Period for calculation"
    )
    
    factor = ParameterDescriptor(
        default=2.0,
        type_=float,
        validator=Float(min_val=0.1, max_val=10.0),
        doc="Multiplication factor"
    )
    
    enabled = ParameterDescriptor(
        default=True,
        type_=bool,
        doc="Enable this indicator"
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        print(f"Basic Indicator created with period={self.get_param('period')}, "
              f"factor={self.get_param('factor')}, enabled={self.get_param('enabled')}")
    
    def calculate(self, data):
        """Example calculation using parameters."""
        if not self.get_param('enabled'):
            return None
        
        period = self.get_param('period')
        factor = self.get_param('factor')
        
        # Simple calculation for demonstration
        return sum(data[-period:]) / period * factor


# =============================================================================
# Example 2: Advanced Validation
# =============================================================================

def validate_levels(levels):
    """Custom validator for level parameters."""
    if not isinstance(levels, (list, tuple)):
        return False
    if len(levels) != 2:
        return False
    if not all(isinstance(x, (int, float)) for x in levels):
        return False
    return levels[0] < levels[1]


class AdvancedIndicator(ParameterizedBase):
    """Advanced example with custom validation and complex parameters."""
    
    # Enum-like parameter
    mode = ParameterDescriptor(
        default='simple',
        type_=str,
        validator=OneOf('simple', 'exponential', 'weighted'),
        doc="Calculation mode"
    )
    
    # Complex validation
    levels = ParameterDescriptor(
        default=[20.0, 80.0],
        validator=validate_levels,
        doc="Two threshold levels [lower, upper]"
    )
    
    # Optional parameter
    custom_multiplier = ParameterDescriptor(
        default=None,
        type_=float,
        validator=lambda x: x is None or x > 0,
        doc="Optional custom multiplier"
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Demonstrate parameter access
        print(f"Advanced Indicator:")
        print(f"  Mode: {self.get_param('mode')}")
        print(f"  Levels: {self.get_param('levels')}")
        print(f"  Custom multiplier: {self.get_param('custom_multiplier')}")


# =============================================================================
# Example 3: Parameter Groups and Organization
# =============================================================================

class OrganizedStrategy(ParameterizedBase):
    """Example showing parameter groups and organization."""
    
    # Moving Average parameters
    fast_period = ParameterDescriptor(
        default=10,
        type_=int,
        validator=Int(min_val=1, max_val=100),
        doc="Fast moving average period"
    )
    
    slow_period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=1, max_val=200),
        doc="Slow moving average period"
    )
    
    # Risk management parameters
    risk_pct = ParameterDescriptor(
        default=0.02,
        type_=float,
        validator=Float(min_val=0.001, max_val=0.1),
        doc="Risk percentage per trade"
    )
    
    stop_loss = ParameterDescriptor(
        default=0.05,
        type_=float,
        validator=Float(min_val=0.01, max_val=0.5),
        doc="Stop loss percentage"
    )
    
    # Signal parameters
    signal_threshold = ParameterDescriptor(
        default=0.01,
        type_=float,
        doc="Signal threshold"
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Create parameter groups
        self._param_manager.create_group('MA_PERIODS', ['fast_period', 'slow_period'])
        self._param_manager.create_group('RISK_MGMT', ['risk_pct', 'stop_loss'])
        self._param_manager.create_group('SIGNALS', ['signal_threshold'])
        
        print(f"Strategy created with parameter groups:")
        print(f"  MA Periods: {self._param_manager.get_group_values('MA_PERIODS')}")
        print(f"  Risk Management: {self._param_manager.get_group_values('RISK_MGMT')}")
        print(f"  Signals: {self._param_manager.get_group_values('SIGNALS')}")
    
    def update_ma_periods(self, fast, slow):
        """Update moving average periods as a group."""
        self._param_manager.set_group('MA_PERIODS', {
            'fast_period': fast,
            'slow_period': slow
        })
        print(f"Updated MA periods: fast={fast}, slow={slow}")
    
    def update_risk_management(self, risk_pct, stop_loss):
        """Update risk management parameters as a group."""
        self._param_manager.set_group('RISK_MGMT', {
            'risk_pct': risk_pct,
            'stop_loss': stop_loss
        })
        print(f"Updated risk management: risk={risk_pct}, stop={stop_loss}")


# =============================================================================
# Example 4: Change Callbacks and History
# =============================================================================

class CallbackExample(ParameterizedBase):
    """Example showing parameter change callbacks and history tracking."""
    
    period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=1),
        doc="Calculation period"
    )
    
    threshold = ParameterDescriptor(
        default=0.5,
        type_=float,
        validator=Float(min_val=0.0, max_val=1.0),
        doc="Threshold value"
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Add change callbacks
        self._param_manager.add_change_callback(self.on_period_change, 'period')
        self._param_manager.add_change_callback(self.on_any_change)
        
        print("Callback example created")
    
    def on_period_change(self, name, old_val, new_val):
        """Called when period parameter changes."""
        print(f"Period changed from {old_val} to {new_val}")
        self.recalculate()
    
    def on_any_change(self, name, old_val, new_val):
        """Called when any parameter changes."""
        print(f"Parameter '{name}' changed: {old_val} -> {new_val}")
    
    def recalculate(self):
        """Recalculate when parameters change."""
        print("Recalculating with new parameters...")
    
    def optimize_parameters(self):
        """Example of parameter optimization with history tracking."""
        print("\nStarting parameter optimization...")
        
        # Try different period values
        for period in [10, 15, 20, 25, 30]:
            self.set_param('period', period)
            # Simulate some calculation result
            result = period * 1.5
            print(f"Period {period}: Result {result}")
        
        # Show change history
        print("\nParameter change history:")
        history = self._param_manager.get_change_history('period')
        for old_val, new_val, timestamp in history[-5:]:  # Last 5 changes
            print(f"  {old_val} -> {new_val} at {time.ctime(timestamp)}")


# =============================================================================
# Example 5: Lazy Defaults and Dependencies
# =============================================================================

class AdvancedFeatures(ParameterizedBase):
    """Example showing lazy defaults and parameter dependencies."""
    
    base_period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=1),
        doc="Base calculation period"
    )
    
    multiplier = ParameterDescriptor(
        default=2.0,
        type_=float,
        validator=Float(min_val=1.0),
        doc="Period multiplier"
    )
    
    # This will be computed lazily
    computed_period = ParameterDescriptor(
        default=None,
        type_=int,
        doc="Computed period based on base_period and multiplier"
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Set up lazy default for computed_period
        self._param_manager.set_lazy_default(
            'computed_period',
            lambda: int(self.get_param('base_period') * self.get_param('multiplier'))
        )
        
        # Set up parameter dependencies
        self._param_manager.add_dependency('base_period', 'computed_period')
        self._param_manager.add_dependency('multiplier', 'computed_period')
        
        print(f"Advanced features example:")
        print(f"  Base period: {self.get_param('base_period')}")
        print(f"  Multiplier: {self.get_param('multiplier')}")
        print(f"  Computed period: {self.get_param('computed_period')}")


# =============================================================================
# Example 6: Transaction Support
# =============================================================================

class TransactionExample(ParameterizedBase):
    """Example showing transactional parameter updates."""
    
    param1 = ParameterDescriptor(default=10, type_=int)
    param2 = ParameterDescriptor(default=20, type_=int)
    param3 = ParameterDescriptor(default=30, type_=int)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        print("Transaction example created")
    
    def safe_batch_update(self, values):
        """Safely update multiple parameters with transaction support."""
        print(f"\nStarting transaction with values: {values}")
        
        # Begin transaction
        self._param_manager.begin_transaction()
        
        try:
            # Update multiple parameters
            for name, value in values.items():
                print(f"Setting {name} = {value}")
                self._param_manager.set(name, value)
            
            # Simulate some validation
            if self.get_param('param1') > self.get_param('param2'):
                raise ValueError("param1 must be <= param2")
            
            # Commit if all is well
            self._param_manager.commit_transaction()
            print("Transaction committed successfully")
            
        except Exception as e:
            # Rollback on error
            self._param_manager.rollback_transaction()
            print(f"Transaction rolled back due to error: {e}")
            
        # Show final values
        print(f"Final values: param1={self.get_param('param1')}, "
              f"param2={self.get_param('param2')}, param3={self.get_param('param3')}")


# =============================================================================
# Example 7: Migration from Old System
# =============================================================================

# Simple legacy-style class for demonstration
class LegacyIndicator(ParameterizedBase):
    """Legacy-style indicator using simple parameter definition."""
    
    # Simple parameter definition (old style simulation)
    period = ParameterDescriptor(default=20, type_=int, doc="Period")
    factor = ParameterDescriptor(default=2.0, type_=float, doc="Factor")
    enabled = ParameterDescriptor(default=True, type_=bool, doc="Enabled")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        print(f"Legacy indicator: period={self.p.period}, factor={self.p.factor}")


# New style (enhanced)
class ModernIndicator(ParameterizedBase):
    period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=1, max_val=500),
        doc="Calculation period"
    )
    
    factor = ParameterDescriptor(
        default=2.0,
        type_=float,
        validator=Float(min_val=0.1, max_val=10.0),
        doc="Multiplication factor"
    )
    
    enabled = ParameterDescriptor(
        default=True,
        type_=bool,
        doc="Enable indicator"
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        print(f"Modern indicator: period={self.p.period}, factor={self.p.factor}")


# =============================================================================
# Example 8: Performance Comparison
# =============================================================================

class PerformanceExample:
    """Example comparing performance of old vs new parameter systems."""
    
    def __init__(self):
        self.legacy = LegacyIndicator()
        self.modern = ModernIndicator()
    
    def benchmark_parameter_access(self, iterations=1000000):
        """Benchmark parameter access performance."""
        print(f"\nBenchmarking parameter access ({iterations:,} iterations):")
        
        # Legacy access
        start_time = time.time()
        for _ in range(iterations):
            _ = self.legacy.p.period
        legacy_time = time.time() - start_time
        
        # Modern access (legacy syntax)
        start_time = time.time()
        for _ in range(iterations):
            _ = self.modern.p.period
        modern_legacy_time = time.time() - start_time
        
        # Modern access (new syntax)
        start_time = time.time()
        for _ in range(iterations):
            _ = self.modern.get_param('period')
        modern_new_time = time.time() - start_time
        
        print(f"  Legacy system: {legacy_time:.4f}s ({iterations/legacy_time:,.0f} ops/sec)")
        print(f"  Modern (legacy syntax): {modern_legacy_time:.4f}s ({iterations/modern_legacy_time:,.0f} ops/sec)")
        print(f"  Modern (new syntax): {modern_new_time:.4f}s ({iterations/modern_new_time:,.0f} ops/sec)")
        print(f"  Speedup: {legacy_time/modern_legacy_time:.1f}x faster")


# =============================================================================
# Example 9: Factory Functions and Helper Utilities
# =============================================================================

class FactoryExample(ParameterizedBase):
    """Example using parameter factory functions."""
    
    # Using factory functions for common parameter types
    price_param = FloatParam(
        default=100.0,
        min_val=0.01,
        max_val=10000.0,
        doc="Price parameter with validation"
    )
    
    enabled_param = BoolParam(
        default=True,
        doc="Boolean parameter"
    )
    
    name_param = StringParam(
        default="example",
        min_length=1,
        max_length=50,
        doc="String parameter with length validation"
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        print(f"Factory example: price={self.get_param('price_param')}, "
              f"enabled={self.get_param('enabled_param')}, "
              f"name='{self.get_param('name_param')}'")


# =============================================================================
# Example 10: Error Handling and Debugging
# =============================================================================

class ErrorHandlingExample(ParameterizedBase):
    """Example showing error handling and debugging features."""
    
    period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=1, max_val=100),
        doc="Period must be between 1 and 100"
    )
    
    ratio = ParameterDescriptor(
        default=0.5,
        type_=float,
        validator=Float(min_val=0.0, max_val=1.0),
        doc="Ratio must be between 0.0 and 1.0"
    )
    
    def demonstrate_error_handling(self):
        """Demonstrate various error scenarios."""
        print("\nDemonstrating error handling:")
        
        # Valid parameter setting
        try:
            self.set_param('period', 50)
            print(f"✓ Set period to 50: {self.get_param('period')}")
        except Exception as e:
            print(f"✗ Error setting period: {e}")
        
        # Invalid type
        try:
            self.set_param('period', "invalid")
            print(f"✓ Set period to string")
        except (ParameterValidationError, ValueError) as e:
            print(f"✗ Expected validation error: {e}")
        
        # Out of range
        try:
            self.set_param('period', 200)
            print(f"✓ Set period to 200")
        except (ParameterValidationError, ValueError) as e:
            print(f"✗ Expected range error: {e}")
        
        # Accessing non-existent parameter
        try:
            value = self.get_param('nonexistent')
            print(f"✓ Got nonexistent parameter: {value}")
        except ParameterAccessError as e:
            print(f"✗ Expected access error: {e}")
        
        # Parameter validation summary
        errors = self.validate_params()
        if errors:
            print(f"Validation errors: {errors}")
        else:
            print("✓ All parameters valid")


# =============================================================================
# Main Demonstration Function
# =============================================================================

def run_examples():
    """Run all parameter system examples."""
    print("=" * 80)
    print("Backtrader New Parameter System - Comprehensive Examples")
    print("=" * 80)
    
    # Example 1: Basic Usage
    print("\n1. Basic Parameter Usage:")
    print("-" * 40)
    basic = BasicIndicator(period=15, factor=1.5)
    result = basic.calculate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    print(f"Calculation result: {result}")
    
    # Example 2: Advanced Validation
    print("\n2. Advanced Validation:")
    print("-" * 40)
    try:
        advanced = AdvancedIndicator(
            mode='exponential',
            levels=[10.0, 90.0],
            custom_multiplier=1.5
        )
    except Exception as e:
        print(f"Error: {e}")
    
    # Example 3: Parameter Groups
    print("\n3. Parameter Groups and Organization:")
    print("-" * 40)
    strategy = OrganizedStrategy(fast_period=5, slow_period=15)
    strategy.update_ma_periods(8, 21)
    strategy.update_risk_management(0.01, 0.03)
    
    # Example 4: Callbacks and History
    print("\n4. Change Callbacks and History:")
    print("-" * 40)
    callback_example = CallbackExample()
    callback_example.set_param('period', 25)
    callback_example.set_param('threshold', 0.7)
    callback_example.optimize_parameters()
    
    # Example 5: Advanced Features
    print("\n5. Lazy Defaults and Dependencies:")
    print("-" * 40)
    advanced_features = AdvancedFeatures(base_period=10, multiplier=3.0)
    print(f"After changing base_period to 15:")
    advanced_features.set_param('base_period', 15)
    print(f"Computed period: {advanced_features.get_param('computed_period')}")
    
    # Example 6: Transactions
    print("\n6. Transaction Support:")
    print("-" * 40)
    transaction_example = TransactionExample()
    
    # Successful transaction
    transaction_example.safe_batch_update({
        'param1': 5,
        'param2': 10,
        'param3': 15
    })
    
    # Failed transaction (will rollback)
    transaction_example.safe_batch_update({
        'param1': 25,  # This will be > param2, causing rollback
        'param2': 10,
        'param3': 35
    })
    
    # Example 7: Migration Comparison
    print("\n7. Migration from Old System:")
    print("-" * 40)
    
    # Show both systems work
    legacy = LegacyIndicator()
    modern = ModernIndicator()
    
    # Show compatibility
    print(f"Legacy access: {legacy.p.period}")
    print(f"Modern legacy access: {modern.p.period}")
    print(f"Modern new access: {modern.get_param('period')}")
    
    # Example 8: Performance
    print("\n8. Performance Comparison:")
    print("-" * 40)
    perf = PerformanceExample()
    perf.benchmark_parameter_access(100000)  # Reduced iterations for demo
    
    # Example 9: Factory Functions
    print("\n9. Factory Functions:")
    print("-" * 40)
    factory = FactoryExample(price_param=150.0, name_param="custom_name")
    
    # Example 10: Error Handling
    print("\n10. Error Handling and Debugging:")
    print("-" * 40)
    error_example = ErrorHandlingExample()
    error_example.demonstrate_error_handling()
    
    # Parameter Information
    print("\n11. Parameter Information and Introspection:")
    print("-" * 40)
    info = error_example.get_param_info()
    for param_name, param_info in info.items():
        print(f"  {param_name}: {param_info}")
    
    print("\n" + "=" * 80)
    print("All examples completed successfully!")
    print("=" * 80)


if __name__ == '__main__':
    run_examples() 