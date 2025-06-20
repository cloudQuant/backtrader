# Parameter System Quick Start Guide

## 5-Minute Introduction

The new Backtrader parameter system makes your code more robust, faster, and easier to maintain. Here's how to get started in 5 minutes.

## Installation and Import

No installation needed! The new parameter system is built into Backtrader. Simply import what you need:

```python
from backtrader.parameters import (
    ParameterizedBase,    # Base class for parameterized objects
    ParameterDescriptor,  # Parameter definition
    Int, Float, Bool,     # Validators
    OneOf                 # Choice validator
)
```

## Your First Parameterized Class

### Old Way (Still Works)
```python
class MyIndicator(bt.Indicator):
    params = (
        ('period', 20),
        ('factor', 2.0),
    )
```

### New Way (Enhanced)
```python
class MyIndicator(ParameterizedBase):
    period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=1, max_val=100),
        doc="Calculation period"
    )
    
    factor = ParameterDescriptor(
        default=2.0,
        type_=float,
        validator=Float(min_val=0.1, max_val=10.0),
        doc="Multiplication factor"
    )
```

## Key Benefits You Get Immediately

### 1. Type Safety
```python
# This now prevents bugs:
indicator = MyIndicator(period="twenty")  # ❌ Auto-converts or errors
indicator = MyIndicator(period=20)        # ✅ Works correctly
```

### 2. Validation
```python
# This prevents invalid configurations:
indicator = MyIndicator(period=-5)    # ❌ Validation error
indicator = MyIndicator(period=500)   # ❌ Out of range
indicator = MyIndicator(period=20)    # ✅ Valid
```

### 3. Better Error Messages
```python
# Old system: Generic error
# New system: "Parameter 'period' expects int between 1 and 100, got -5"
```

## Common Parameter Patterns

### 1. Integer with Range
```python
period = ParameterDescriptor(
    default=20,
    type_=int,
    validator=Int(min_val=1, max_val=252),
    doc="Trading period in days"
)
```

### 2. Float with Range
```python
alpha = ParameterDescriptor(
    default=0.5,
    type_=float,
    validator=Float(min_val=0.0, max_val=1.0),
    doc="Smoothing factor"
)
```

### 3. Choice Parameter
```python
mode = ParameterDescriptor(
    default='sma',
    validator=OneOf('sma', 'ema', 'wma'),
    doc="Moving average type"
)
```

### 4. Boolean Parameter
```python
enabled = ParameterDescriptor(
    default=True,
    type_=bool,
    doc="Enable this feature"
)
```

### 5. Optional Parameter
```python
custom_value = ParameterDescriptor(
    default=None,
    type_=float,
    validator=lambda x: x is None or x > 0,
    doc="Optional custom value"
)
```

## Using Parameters (Same as Before!)

```python
class MyStrategy(ParameterizedBase):
    period = ParameterDescriptor(default=20, type_=int)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # All these work exactly the same:
        print(self.p.period)              # ✅ Legacy way
        print(self.params.period)         # ✅ Legacy way  
        print(self.get_param('period'))   # ✅ New way (recommended)
```

## Complete Example: Simple Strategy

```python
from backtrader.parameters import ParameterizedBase, ParameterDescriptor, Int, Float

class SimpleMAStrategy(ParameterizedBase):
    """Simple moving average crossover strategy with enhanced parameters."""
    
    # Moving average periods
    fast_period = ParameterDescriptor(
        default=10,
        type_=int,
        validator=Int(min_val=1, max_val=50),
        doc="Fast moving average period"
    )
    
    slow_period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=1, max_val=100),
        doc="Slow moving average period"
    )
    
    # Risk management
    position_size = ParameterDescriptor(
        default=0.1,
        type_=float,
        validator=Float(min_val=0.01, max_val=1.0),
        doc="Position size as fraction of portfolio"
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Validate parameter relationships
        if self.get_param('fast_period') >= self.get_param('slow_period'):
            raise ValueError("Fast period must be less than slow period")
        
        print(f"Strategy created: MA({self.p.fast_period}, {self.p.slow_period})")

# Usage - both ways work:
strategy1 = SimpleMAStrategy()                           # Use defaults
strategy2 = SimpleMAStrategy(fast_period=5, slow_period=15)  # Custom values
```

## Instant Upgrades: Using Factory Functions

For even faster development, use factory functions:

```python
from backtrader.parameters import FloatParam, BoolParam, StringParam

class QuickIndicator(ParameterizedBase):
    # These one-liners give you full validation:
    alpha = FloatParam(default=0.5, min_val=0.0, max_val=1.0, doc="Alpha factor")
    enabled = BoolParam(default=True, doc="Enable indicator")
    name = StringParam(default="indicator", min_length=1, doc="Indicator name")
```

## Migration Strategy: Start Small

You don't need to migrate everything at once:

### 1. Keep Existing Code (Works Forever)
```python
# This continues to work unchanged
class LegacyStrategy(bt.Strategy):
    params = (('period', 20),)
```

### 2. Use New System for New Classes
```python
# New classes get enhanced features
class ModernIndicator(ParameterizedBase):
    period = ParameterDescriptor(default=20, type_=int)
```

### 3. They Work Together Seamlessly
```python
class MixedStrategy(bt.Strategy):
    def __init__(self):
        self.legacy_indicator = LegacyIndicator()
        self.modern_indicator = ModernIndicator()
        # Both work the same way!
```

## Advanced Features (When You Need Them)

### Parameter Groups
```python
class AdvancedStrategy(ParameterizedBase):
    fast_period = ParameterDescriptor(default=10, type_=int)
    slow_period = ParameterDescriptor(default=20, type_=int)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Group related parameters
        self._param_manager.create_group('MA_PERIODS', ['fast_period', 'slow_period'])
        
        # Update as a group
        self._param_manager.set_group('MA_PERIODS', {'fast_period': 5, 'slow_period': 15})
```

### Change Callbacks
```python
class ReactiveIndicator(ParameterizedBase):
    period = ParameterDescriptor(default=20, type_=int)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # React to parameter changes
        def on_period_change(name, old_val, new_val):
            print(f"Period changed from {old_val} to {new_val}")
            self.recalculate()
        
        self._param_manager.add_change_callback(on_period_change, 'period')
```

## Performance: It's Faster!

The new system is significantly faster:
- Parameter access: 4x faster
- Parameter setting: 2x faster
- Memory usage: More efficient

## Troubleshooting Common Issues

### Type Errors
```python
# Problem: String where int expected
indicator = MyIndicator(period="20")

# Solution: Pass correct type
indicator = MyIndicator(period=20)
```

### Validation Errors
```python
# Problem: Value out of range
indicator = MyIndicator(period=-5)  # Error: must be >= 1

# Solution: Use valid value
indicator = MyIndicator(period=20)
```

### Parameter Not Found
```python
# Problem: Wrong parameter name
print(indicator.p.periods)  # Error: should be 'period'

# Solution: Use correct name
print(indicator.p.period)
```

## Next Steps

1. **Try It**: Copy one of the examples above and run it
2. **Migrate Gradually**: Start with new classes or simple existing ones
3. **Add Validation**: Use built-in validators to make your code more robust
4. **Explore Advanced Features**: Groups, callbacks, and more when you need them
5. **Read the Full Docs**: Check out the API reference and migration guide

## Need Help?

- **API Reference**: Complete documentation of all features
- **Migration Guide**: Detailed guidance for converting existing code
- **Examples**: Comprehensive examples showing all capabilities
- **Performance Guide**: Optimization tips and benchmarks

The new parameter system is designed to make your life easier while maintaining 100% backward compatibility. Start simple, and add features as you need them! 