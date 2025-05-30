"""
New Parameter System for Backtrader

This module implements a modern parameter system that replaces the metaclass-based
parameter handling with descriptor-based approach. This provides better type safety,
validation, and maintainability while maintaining backward compatibility.

Key Components:
- ParameterDescriptor: Core descriptor for parameter handling
- ParameterManager: Parameter storage and management
- ParameterizedBase: Base class for parameterized objects
- Type checking and validation mechanisms
- Python 3.6+ __set_name__ support
"""

import sys
import inspect
from typing import Any, Dict, List, Optional, Union, Callable, Type, get_type_hints
from collections import OrderedDict
from .utils.py3 import string_types


class ParameterDescriptor:
    """
    Advanced parameter descriptor with type checking and validation.
    
    This descriptor replaces the metaclass-based parameter system with a more
    modern and maintainable approach. It provides:
    
    - Automatic type checking and conversion
    - Value validation
    - Default value handling
    - Documentation support
    - Python 3.6+ __set_name__ support
    """
    
    def __init__(self, 
                 default: Any = None,
                 type_: Optional[Type] = None, 
                 validator: Optional[Callable[[Any], bool]] = None,
                 doc: Optional[str] = None,
                 name: Optional[str] = None):
        """
        Initialize parameter descriptor.
        
        Args:
            default: Default value for the parameter
            type_: Expected type for the parameter (enables type checking)
            validator: Function to validate parameter values
            doc: Documentation string for the parameter
            name: Parameter name (usually set by __set_name__)
        """
        self.default = default
        self.type_ = type_
        self.validator = validator
        self.doc = doc
        self.name = name
        
        # Internal attribute name where the value is stored
        self._attr_name = None
    
    def __set_name__(self, owner, name):
        """
        Called when the descriptor is assigned to a class attribute.
        This is a Python 3.6+ feature that automatically sets the parameter name.
        """
        self.name = name
        self._attr_name = f'_param_{name}'
        
        # Register this descriptor with the owner class
        if not hasattr(owner, '_parameter_descriptors'):
            owner._parameter_descriptors = {}
        owner._parameter_descriptors[name] = self
    
    def __get__(self, obj, objtype=None):
        """Get parameter value from object instance."""
        if obj is None:
            return self
        
        # Get value from parameter manager
        if hasattr(obj, '_param_manager'):
            return obj._param_manager.get(self.name, self.default)
        
        # Fallback: get from object attribute
        return getattr(obj, self._attr_name, self.default)
    
    def __set__(self, obj, value):
        """Set parameter value on object instance with validation."""
        # Type checking
        if self.type_ is not None and value is not None:
            if not isinstance(value, self.type_):
                try:
                    # Attempt type conversion
                    value = self.type_(value)
                except (ValueError, TypeError) as e:
                    raise TypeError(
                        f"Parameter '{self.name}' expects {self.type_.__name__}, "
                        f"got {type(value).__name__}. Conversion failed: {e}"
                    )
        
        # Value validation
        if self.validator is not None:
            if not self.validator(value):
                raise ValueError(f"Invalid value for parameter '{self.name}': {value}")
        
        # Set value through parameter manager
        if hasattr(obj, '_param_manager'):
            obj._param_manager.set(self.name, value)
        else:
            # Fallback: set as object attribute
            setattr(obj, self._attr_name, value)
    
    def __delete__(self, obj):
        """Delete parameter value, reverting to default."""
        if hasattr(obj, '_param_manager'):
            obj._param_manager.reset(self.name)
        elif hasattr(obj, self._attr_name):
            delattr(obj, self._attr_name)
    
    def validate(self, value: Any) -> bool:
        """
        Validate a value for this parameter.
        
        Args:
            value: Value to validate
            
        Returns:
            True if value is valid, False otherwise
        """
        try:
            # Type check
            if self.type_ is not None and value is not None:
                if not isinstance(value, self.type_):
                    self.type_(value)  # Test conversion
            
            # Custom validation
            if self.validator is not None:
                return self.validator(value)
            
            return True
        except (ValueError, TypeError):
            return False
    
    def get_type_info(self) -> Dict[str, Any]:
        """Get type information for this parameter."""
        return {
            'name': self.name,
            'type': self.type_,
            'default': self.default,
            'has_validator': self.validator is not None,
            'doc': self.doc
        }


class ParameterManager:
    """
    Parameter storage and management system.
    
    This class manages parameter values for an object, replacing the functionality
    of AutoInfoClass. It provides efficient storage, inheritance support, and
    batch operations.
    """
    
    def __init__(self, descriptors: Dict[str, ParameterDescriptor], 
                 initial_values: Optional[Dict[str, Any]] = None):
        """
        Initialize parameter manager.
        
        Args:
            descriptors: Dictionary of parameter descriptors
            initial_values: Initial parameter values
        """
        self._descriptors = descriptors.copy()
        self._values = {}
        self._defaults = {name: desc.default for name, desc in descriptors.items()}
        
        if initial_values:
            self.update(initial_values)
    
    def get(self, name: str, default: Any = None) -> Any:
        """
        Get parameter value.
        
        Args:
            name: Parameter name
            default: Default value if parameter not found
            
        Returns:
            Parameter value
        """
        if name in self._values:
            return self._values[name]
        elif name in self._defaults:
            return self._defaults[name]
        else:
            return default
    
    def set(self, name: str, value: Any) -> None:
        """
        Set parameter value with validation.
        
        Args:
            name: Parameter name
            value: Parameter value
            
        Raises:
            AttributeError: If parameter doesn't exist
            TypeError: If type validation fails
            ValueError: If value validation fails
        """
        if name not in self._descriptors:
            raise AttributeError(f"Unknown parameter: {name}")
        
        # Validate through descriptor
        descriptor = self._descriptors[name]
        
        # Type checking
        if descriptor.type_ is not None and value is not None:
            if not isinstance(value, descriptor.type_):
                try:
                    value = descriptor.type_(value)
                except (ValueError, TypeError) as e:
                    raise TypeError(
                        f"Parameter '{name}' expects {descriptor.type_.__name__}, "
                        f"got {type(value).__name__}. Conversion failed: {e}"
                    )
        
        # Value validation
        if descriptor.validator is not None:
            if not descriptor.validator(value):
                raise ValueError(f"Invalid value for parameter '{name}': {value}")
        
        self._values[name] = value
    
    def reset(self, name: str) -> None:
        """
        Reset parameter to default value.
        
        Args:
            name: Parameter name
        """
        if name in self._values:
            del self._values[name]
    
    def update(self, values: Union[Dict[str, Any], 'ParameterManager']) -> None:
        """
        Batch update parameters.
        
        Args:
            values: Dictionary of values or another ParameterManager
        """
        if isinstance(values, dict):
            for name, value in values.items():
                if name in self._descriptors:
                    self.set(name, value)
        elif isinstance(values, ParameterManager):
            for name, value in values._values.items():
                if name in self._descriptors:
                    self.set(name, value)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with all current values."""
        result = self._defaults.copy()
        result.update(self._values)
        return result
    
    def keys(self):
        """Get all parameter names."""
        return set(self._defaults.keys()) | set(self._values.keys())
    
    def items(self):
        """Get all parameter items."""
        return self.to_dict().items()
    
    def values(self):
        """Get all parameter values."""
        return self.to_dict().values()
    
    def __getitem__(self, name):
        return self.get(name)
    
    def __setitem__(self, name, value):
        self.set(name, value)
    
    def __contains__(self, name):
        return name in self._descriptors
    
    def __len__(self):
        return len(self._descriptors)
    
    def __iter__(self):
        return iter(self.keys())
    
    def copy(self) -> 'ParameterManager':
        """Create a copy of this parameter manager."""
        new_manager = ParameterManager(self._descriptors)
        new_manager._values = self._values.copy()
        return new_manager
    
    def inherit_from(self, parent: 'ParameterManager') -> None:
        """
        Inherit parameter values from parent manager.
        
        Args:
            parent: Parent parameter manager
        """
        for name, value in parent._values.items():
            if name in self._descriptors and name not in self._values:
                self._values[name] = value


class ParameterAccessor:
    """
    Backward compatibility accessor for parameters.
    
    This class provides the same interface as the old parameter system
    (obj.params.param_name and obj.p.param_name) while using the new
    descriptor-based system internally.
    """
    
    def __init__(self, param_manager: ParameterManager):
        """
        Initialize parameter accessor.
        
        Args:
            param_manager: Underlying parameter manager
        """
        self._manager = param_manager
    
    def __getattr__(self, name):
        """Get parameter value by attribute access."""
        return self._manager.get(name)
    
    def __setattr__(self, name, value):
        """Set parameter value by attribute access."""
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            self._manager.set(name, value)
    
    def __getitem__(self, name):
        """Get parameter value by index access."""
        return self._manager.get(name)
    
    def __setitem__(self, name, value):
        """Set parameter value by index access."""
        self._manager.set(name, value)
    
    def __contains__(self, name):
        """Check if parameter exists."""
        return name in self._manager
    
    def __iter__(self):
        """Iterate over parameter names."""
        return iter(self._manager.keys())
    
    def __len__(self):
        """Get number of parameters."""
        return len(self._manager)
    
    def _getitems(self):
        """Backward compatibility method for old parameter system."""
        return self._manager.items()
    
    def _getkeys(self):
        """Backward compatibility method for old parameter system."""
        return list(self._manager.keys())
    
    def _getvalues(self):
        """Backward compatibility method for old parameter system."""
        return list(self._manager.values())


class ParameterizedMeta(type):
    """
    Metaclass for parameterized classes.
    
    This metaclass collects parameter descriptors from the class definition
    and its base classes, creating a unified parameter system. It's designed
    to be lightweight and focused only on parameter collection.
    """
    
    def __new__(mcs, name, bases, namespace, **kwargs):
        """Create a new parameterized class."""
        # Collect parameter descriptors from all bases
        all_descriptors = {}
        
        # First, collect from base classes (in MRO order)
        for base in reversed(bases):
            if hasattr(base, '_parameter_descriptors'):
                all_descriptors.update(base._parameter_descriptors)
        
        # Then, collect from current class namespace
        current_descriptors = {}
        for key, value in list(namespace.items()):
            if isinstance(value, ParameterDescriptor):
                current_descriptors[key] = value
                # Set name if not already set
                if value.name is None:
                    value.name = key
                    value._attr_name = f'_param_{key}'
        
        all_descriptors.update(current_descriptors)
        
        # Store collected descriptors in the namespace
        namespace['_parameter_descriptors'] = all_descriptors
        
        # Create the class
        cls = super().__new__(mcs, name, bases, namespace)
        
        return cls


class ParameterizedBase(metaclass=ParameterizedMeta):
    """
    Base class for objects with parameters.
    
    This class provides the modern parameter system interface while maintaining
    backward compatibility with the old MetaParams-based system. It automatically
    handles parameter initialization, validation, and access.
    """
    
    def __init__(self, **kwargs):
        """
        Initialize parameterized object.
        
        Args:
            **kwargs: Keyword arguments including parameter values
        """
        # Initialize parameter manager
        descriptors = getattr(self.__class__, '_parameter_descriptors', {})
        self._param_manager = ParameterManager(descriptors)
        
        # Separate parameter kwargs from other kwargs
        param_kwargs = {}
        other_kwargs = {}
        
        for key, value in kwargs.items():
            if key in descriptors:
                param_kwargs[key] = value
            else:
                other_kwargs[key] = value
        
        # Set parameter values
        if param_kwargs:
            self._param_manager.update(param_kwargs)
        
        # Create backward compatibility accessors
        self.params = ParameterAccessor(self._param_manager)
        self.p = self.params  # Short alias
        
        # Call parent __init__ with remaining kwargs
        super().__init__(**other_kwargs)
    
    def get_param(self, name: str, default: Any = None) -> Any:
        """
        Get parameter value.
        
        Args:
            name: Parameter name
            default: Default value if parameter not found
            
        Returns:
            Parameter value
        """
        return self._param_manager.get(name, default)
    
    def set_param(self, name: str, value: Any) -> None:
        """
        Set parameter value.
        
        Args:
            name: Parameter name
            value: Parameter value
        """
        self._param_manager.set(name, value)
    
    def get_param_info(self) -> Dict[str, Dict[str, Any]]:
        """
        Get information about all parameters.
        
        Returns:
            Dictionary mapping parameter names to their type information
        """
        descriptors = getattr(self.__class__, '_parameter_descriptors', {})
        return {name: desc.get_type_info() for name, desc in descriptors.items()}
    
    def validate_params(self) -> List[str]:
        """
        Validate all current parameter values.
        
        Returns:
            List of validation error messages (empty if all valid)
        """
        errors = []
        descriptors = getattr(self.__class__, '_parameter_descriptors', {})
        
        for name, descriptor in descriptors.items():
            current_value = self._param_manager.get(name)
            if not descriptor.validate(current_value):
                errors.append(f"Parameter '{name}' has invalid value: {current_value}")
        
        return errors


# Type checking helper functions
def Int(min_val: Optional[int] = None, max_val: Optional[int] = None) -> Callable[[Any], bool]:
    """
    Create a validator for integer parameters with optional range checking.
    
    Args:
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        
    Returns:
        Validator function
    """
    def validator(value):
        if not isinstance(value, int):
            return False
        if min_val is not None and value < min_val:
            return False
        if max_val is not None and value > max_val:
            return False
        return True
    return validator


def Float(min_val: Optional[float] = None, max_val: Optional[float] = None) -> Callable[[Any], bool]:
    """
    Create a validator for float parameters with optional range checking.
    
    Args:
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        
    Returns:
        Validator function
    """
    def validator(value):
        if not isinstance(value, (int, float)):
            return False
        if min_val is not None and value < min_val:
            return False
        if max_val is not None and value > max_val:
            return False
        return True
    return validator


def OneOf(*choices) -> Callable[[Any], bool]:
    """
    Create a validator that checks if value is one of the given choices.
    
    Args:
        *choices: Valid choices
        
    Returns:
        Validator function
    """
    def validator(value):
        return value in choices
    return validator


def String(min_length: Optional[int] = None, max_length: Optional[int] = None) -> Callable[[Any], bool]:
    """
    Create a validator for string parameters with optional length checking.
    
    Args:
        min_length: Minimum string length
        max_length: Maximum string length
        
    Returns:
        Validator function
    """
    def validator(value):
        if not isinstance(value, string_types):
            return False
        if min_length is not None and len(value) < min_length:
            return False
        if max_length is not None and len(value) > max_length:
            return False
        return True
    return validator


# Legacy compatibility functions
def create_param_descriptor(name: str, default: Any = None, doc: str = None) -> ParameterDescriptor:
    """
    Create a parameter descriptor for backward compatibility.
    
    Args:
        name: Parameter name
        default: Default value
        doc: Documentation
        
    Returns:
        ParameterDescriptor instance
    """
    return ParameterDescriptor(default=default, doc=doc, name=name)


def derive_params(base_params, new_params, other_base_params=None):
    """
    Create derived parameter set for backward compatibility.
    
    This function mimics the behavior of AutoInfoClass._derive() for
    compatibility with existing code during the transition period.
    """
    # This is a simplified implementation for testing
    # In practice, this would need to handle all the complexity of the original
    combined_params = {}
    
    # Add base parameters
    if hasattr(base_params, '_parameter_descriptors'):
        combined_params.update(base_params._parameter_descriptors)
    
    # Add other base parameters
    if other_base_params:
        for base in other_base_params:
            if hasattr(base, '_parameter_descriptors'):
                combined_params.update(base._parameter_descriptors)
    
    # Add new parameters
    if isinstance(new_params, (list, tuple)):
        for i, param in enumerate(new_params):
            if isinstance(param, (list, tuple)) and len(param) >= 2:
                name, default = param[0], param[1]
                combined_params[name] = ParameterDescriptor(default=default, name=name)
            else:
                # Handle other formats as needed
                pass
    
    return combined_params 