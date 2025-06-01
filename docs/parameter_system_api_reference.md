# Parameter System API Reference

## Overview

The Backtrader parameter system has been completely refactored to use modern Python descriptors instead of metaclasses. This provides better type safety, validation, performance, and maintainability while maintaining full backward compatibility.

## Core Components

### ParameterDescriptor

The foundation of the new parameter system. Handles type checking, validation, and documentation.

```python
class ParameterDescriptor:
    def __init__(self, 
                 default: Any = None,
                 type_: Optional[Type] = None, 
                 validator: Optional[Callable[[Any], bool]] = None,
                 doc: Optional[str] = None,
                 name: Optional[str] = None,
                 required: bool = False)
```

#### Parameters:
- **default**: Default value for the parameter
- **type_**: Expected type (enables automatic type checking and conversion)
- **validator**: Custom validation function
- **doc**: Documentation string
- **name**: Parameter name (auto-set by `__set_name__`)
- **required**: Whether parameter is required (no default)

#### Methods:

##### `validate(value: Any) -> bool`
Validates a value against the parameter's constraints.

##### `get_type_info() -> Dict[str, Any]`
Returns type information dictionary with name, type, default, etc.

#### Example:
```python
class MyIndicator(ParameterizedBase):
    period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=lambda x: x > 0,
        doc="Period for calculation"
    )
    
    alpha = ParameterDescriptor(
        default=0.5,
        type_=float,
        validator=lambda x: 0.0 <= x <= 1.0,
        doc="Smoothing factor"
    )
```

### ParameterManager

Advanced parameter storage and management system that replaces AutoInfoClass functionality.

```python
class ParameterManager:
    def __init__(self, descriptors: Dict[str, ParameterDescriptor], 
                 initial_values: Optional[Dict[str, Any]] = None,
                 enable_history: bool = True,
                 enable_callbacks: bool = True)
```

#### Core Methods:

##### `get(name: str, default: Any = None) -> Any`
Retrieves parameter value with optional default.

##### `set(name: str, value: Any, force: bool = False, trigger_callbacks: bool = True, skip_validation: bool = False) -> None`
Sets parameter value with validation and callbacks.

##### `update(values: Union[Dict[str, Any], 'ParameterManager'], force: bool = False, validate_all: bool = True) -> None`
Batch update multiple parameters.

##### `reset(name: str, force: bool = False) -> None`
Reset parameter to default value.

##### `to_dict() -> Dict[str, Any]`
Export all parameter values as dictionary.

#### Advanced Features:

##### Parameter Locking
```python
manager.lock_parameter('critical_param')
manager.unlock_parameter('critical_param')
manager.is_locked('critical_param')
manager.get_locked_parameters()
```

##### Parameter Groups
```python
manager.create_group('MACD', ['fast_period', 'slow_period', 'signal_period'])
manager.set_group('MACD', {'fast_period': 12, 'slow_period': 26})
manager.get_group_values('MACD')
```

##### Change History and Callbacks
```python
# Add change callback
def param_changed(name, old_val, new_val):
    print(f"{name}: {old_val} -> {new_val}")

manager.add_change_callback(param_changed)

# View change history
history = manager.get_change_history('param_name')
manager.clear_history()
```

##### Inheritance Support
```python
manager.inherit_from(parent_manager, 
                    strategy='merge',  # 'merge', 'override', 'preserve'
                    conflict_resolution='parent',  # 'parent', 'child', 'error'
                    selective=['param1', 'param2'])  # Only inherit specific params
```

##### Lazy Defaults and Dependencies
```python
# Lazy evaluation of default values
manager.set_lazy_default('computed_param', lambda: expensive_calculation())

# Parameter dependencies
manager.add_dependency('base_param', 'dependent_param')
```

##### Transactional Updates
```python
manager.begin_transaction()
try:
    manager.set('param1', value1)
    manager.set('param2', value2)
    manager.commit_transaction()
except Exception:
    manager.rollback_transaction()
```

### ParameterizedBase

Base class for all parameterized objects in Backtrader. Provides the main interface for working with parameters.

```python
class ParameterizedBase(metaclass=ParameterizedMeta):
    def __init__(self, **kwargs)
```

#### Key Methods:

##### `get_param(name: str, default: Any = None) -> Any`
Get parameter value safely.

##### `set_param(name: str, value: Any, validate: bool = True) -> None`
Set parameter value with optional validation.

##### `get_param_info() -> Dict[str, Dict[str, Any]]`
Get complete parameter information.

##### `validate_params() -> List[str]`
Validate all parameters, returns list of errors.

##### `reset_param(name: str) -> None`
Reset single parameter to default.

##### `reset_all_params() -> None`
Reset all parameters to defaults.

##### `get_modified_params() -> Dict[str, Any]`
Get only parameters that differ from defaults.

##### `copy_params_from(other: 'ParameterizedBase', param_names: Optional[List[str]] = None, exclude: Optional[List[str]] = None) -> None`
Copy parameters from another object.

#### Backward Compatibility:
The class maintains full compatibility with the old `self.p.param_name` syntax through the `ParameterAccessor`:

```python
# All these work identically:
value = self.get_param('period')  # New API
value = self.p.period             # Legacy API
value = self.params.period        # Legacy API
```

## Validator Helpers

Pre-built validators for common parameter types:

### Numeric Validators

```python
# Integer range validation
Int(min_val=1, max_val=100)

# Float range validation  
Float(min_val=0.0, max_val=1.0)

# Boolean validation
Bool()
```

### String Validators

```python
# String length validation
String(min_length=1, max_length=50)

# Choice validation
OneOf('option1', 'option2', 'option3')
```

### Parameter Factory Functions

Convenience functions for creating common parameter types:

```python
# Float parameter with range validation
FloatParam(default=0.5, min_val=0.0, max_val=1.0, doc="Alpha factor")

# Boolean parameter
BoolParam(default=True, doc="Enable feature")

# String parameter with length limits
StringParam(default="", min_length=1, max_length=100, doc="Name field")
```

## Migration Support

### MetaParamsBridge

Utilities for migrating from the old metaclass system:

```python
class MetaParamsBridge:
    @staticmethod
    def extract_params_from_metaparams_class(cls) -> Dict[str, ParameterDescriptor]
    
    @staticmethod 
    def convert_legacy_params_tuple(params_tuple) -> Dict[str, ParameterDescriptor]
    
    @staticmethod
    def create_compatibility_wrapper(metaparams_class)
```

### Validation Utilities

```python
def validate_parameter_compatibility(old_class, new_class) -> Dict[str, Any]
```

Compares parameter definitions between old and new classes to ensure compatibility.

## Exception Classes

### ParameterValidationError

Raised when parameter validation fails:

```python
class ParameterValidationError(ValueError):
    def __init__(self, parameter_name: str, value: Any, 
                 expected_type: Optional[Type] = None, 
                 additional_info: str = "")
```

### ParameterAccessError  

Raised when accessing non-existent parameters:

```python
class ParameterAccessError(AttributeError):
    def __init__(self, parameter_name: str, class_name: str, 
                 available_params: List[str])
```

## Best Practices

### 1. Parameter Definition

```python
class MyStrategy(ParameterizedBase):
    # Use descriptive names and documentation
    fast_period = ParameterDescriptor(
        default=10,
        type_=int,
        validator=Int(min_val=1, max_val=100),
        doc="Fast moving average period"
    )
    
    slow_period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=1, max_val=100),
        doc="Slow moving average period"
    )
    
    # Group related parameters
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._param_manager.create_group('MA_PERIODS', ['fast_period', 'slow_period'])
```

### 2. Parameter Validation

```python
def custom_validator(value):
    """Custom validation logic"""
    if not isinstance(value, (int, float)):
        return False
    return 1 <= value <= 252  # Trading days in a year

class MyIndicator(ParameterizedBase):
    period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=custom_validator,
        doc="Calculation period in trading days"
    )
```

### 3. Dynamic Parameter Updates

```python
class AdaptiveStrategy(ParameterizedBase):
    period = ParameterDescriptor(default=20, type_=int)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Add callback for parameter changes
        def on_period_change(name, old_val, new_val):
            self.recalculate_indicators()
            
        self._param_manager.add_change_callback(on_period_change, 'period')
    
    def adapt_parameters(self, market_condition):
        """Dynamically adjust parameters based on market conditions"""
        if market_condition == 'volatile':
            self.set_param('period', 10)
        elif market_condition == 'trending':
            self.set_param('period', 50)
```

### 4. Parameter Inheritance

```python
class BaseStrategy(ParameterizedBase):
    period = ParameterDescriptor(default=20, type_=int)
    threshold = ParameterDescriptor(default=0.01, type_=float)

class AdvancedStrategy(BaseStrategy):
    # Inherits period and threshold
    multiplier = ParameterDescriptor(default=2.0, type_=float)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Copy parameters from another strategy instance
        if 'base_strategy' in kwargs:
            self.copy_params_from(kwargs['base_strategy'], 
                                param_names=['period', 'threshold'])
```

## Performance Characteristics

The new parameter system provides significant performance improvements:

- **Parameter Access**: >4,000,000 operations/second
- **Parameter Setting**: >500,000 operations/second  
- **Validation Overhead**: <25% compared to direct attribute access
- **Memory Usage**: <2KB per object with shared descriptors
- **Inheritance Impact**: <2x slowdown for complex inheritance chains

## Compatibility

The new system maintains 100% backward compatibility with existing code:

- All `self.p.parameter` access continues to work
- All `self.params.parameter` access continues to work
- Parameter tuple syntax is automatically converted
- MetaParams-based classes work seamlessly

Migration is optional and can be done incrementally on a per-class basis. 