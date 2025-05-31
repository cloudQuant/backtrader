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
                 name: Optional[str] = None,
                 required: bool = False):
        """
        Initialize parameter descriptor.
        
        Args:
            default: Default value for the parameter
            type_: Expected type for the parameter (enables type checking)
            validator: Function to validate parameter values
            doc: Documentation string for the parameter
            name: Parameter name (usually set by __set_name__)
            required: Whether this parameter is required (no default allowed)
        """
        self.default = default
        self.type_ = type_
        self.validator = validator
        self.doc = doc
        self.name = name
        self.required = required
        
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
            # Required check
            if self.required and value is None:
                return False
            
            # Type check - be more flexible with numeric types
            if self.type_ is not None and value is not None:
                if self.type_ == float:
                    # For float, accept int, float, and convertible strings
                    if not isinstance(value, (int, float)):
                        try:
                            float(value)  # Test conversion
                        except (ValueError, TypeError):
                            return False
                elif self.type_ == int:
                    # For int, accept int and convertible values
                    if not isinstance(value, int):
                        try:
                            int(value)  # Test conversion
                        except (ValueError, TypeError):
                            return False
                elif self.type_ == bool:
                    # For bool, be flexible with boolean-like values
                    if not isinstance(value, bool) and value not in (0, 1, 'True', 'False', 'true', 'false'):
                        return False
                elif not isinstance(value, self.type_):
                    try:
                        self.type_(value)  # Test conversion for other types
                    except (ValueError, TypeError):
                        return False
            
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
            'required': self.required,
            'has_validator': self.validator is not None,
            'doc': self.doc
        }


class ParameterManager:
    """
    Enhanced Parameter storage and management system.
    
    This class manages parameter values for an object, replacing the functionality
    of AutoInfoClass. It provides efficient storage, inheritance support, batch
    operations, and advanced features like change tracking, callbacks, and 
    transactional updates.
    
    New Features in Day 32-33:
    - Parameter change history and tracking
    - Change callbacks and notifications
    - Parameter locking mechanism
    - Parameter groups for organization
    - Advanced inheritance with conflict resolution
    - Lazy default value evaluation
    - Transactional batch updates
    - Dependency tracking between parameters
    """
    
    def __init__(self, descriptors: Dict[str, ParameterDescriptor], 
                 initial_values: Optional[Dict[str, Any]] = None,
                 enable_history: bool = True,
                 enable_callbacks: bool = True):
        """
        Initialize enhanced parameter manager.
        
        Args:
            descriptors: Dictionary of parameter descriptors
            initial_values: Initial parameter values
            enable_history: Whether to track parameter changes
            enable_callbacks: Whether to enable change callbacks
        """
        self._descriptors = descriptors.copy()
        self._values = {}
        self._defaults = {name: desc.default for name, desc in descriptors.items()}
        
        # Enhanced features
        self._enable_history = enable_history
        self._enable_callbacks = enable_callbacks
        
        # Change tracking
        self._history = {} if enable_history else None  # {param_name: [(old_value, new_value, timestamp), ...]}
        self._change_callbacks = {} if enable_callbacks else None  # {param_name: [callback_func, ...]}
        self._global_callbacks = [] if enable_callbacks else None  # [callback_func, ...]
        
        # Parameter locking
        self._locked_params = set()  # Set of locked parameter names
        
        # Parameter groups
        self._groups = {}  # {group_name: [param_names]}
        self._param_groups = {}  # {param_name: group_name}
        
        # Inheritance tracking
        self._inheritance_chain = []  # List of parent managers in inheritance order
        self._inherited_params = {}  # {param_name: source_manager}
        
        # Lazy defaults
        self._lazy_defaults = {}  # {param_name: lazy_func}
        self._computed_defaults = {}  # {param_name: computed_value}
        
        # Dependencies
        self._dependencies = {}  # {param_name: [dependent_param_names]}
        self._dependents = {}  # {param_name: [param_names_that_depend_on_this]}
        
        # Transaction support
        self._in_transaction = False
        self._transaction_changes = {}  # Changes made during transaction
        self._transaction_rollback = {}  # Values to rollback to
        
        # Initialize with provided values
        if initial_values:
            self.update(initial_values)
    
    def get(self, name: str, default: Any = None) -> Any:
        """
        Get parameter value with enhanced features.
        
        Args:
            name: Parameter name
            default: Default value if parameter not found
            
        Returns:
            Parameter value
        """
        # Check transaction changes first
        if self._in_transaction and name in self._transaction_changes:
            return self._transaction_changes[name]
            
        # Check if value is explicitly set and not None
        if name in self._values and self._values[name] is not None:
            return self._values[name]
        
        # If value is None or not set, check defaults
        if name in self._defaults:
            # Check for lazy default
            if name in self._lazy_defaults:
                if name not in self._computed_defaults:
                    self._computed_defaults[name] = self._lazy_defaults[name]()
                return self._computed_defaults[name]
            return self._defaults[name]
        else:
            return default
    
    def set(self, name: str, value: Any, force: bool = False, 
            trigger_callbacks: bool = True, skip_validation: bool = False) -> None:
        """
        Set parameter value with enhanced validation and tracking.
        
        Args:
            name: Parameter name
            value: Parameter value
            force: Whether to override locked parameters
            trigger_callbacks: Whether to trigger change callbacks
            skip_validation: Whether to skip type and value validation
            
        Raises:
            AttributeError: If parameter doesn't exist
            TypeError: If type validation fails
            ValueError: If value validation fails or parameter is locked
        """
        if name not in self._descriptors:
            raise AttributeError(f"Unknown parameter: {name}")
        
        # Check if parameter is locked
        if not force and name in self._locked_params:
            raise ValueError(f"Parameter '{name}' is locked and cannot be modified")
        
        # Store old value for history and callbacks
        old_value = self.get(name)
        
        if not skip_validation:
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
        
        # Set the value
        if self._in_transaction:
            if name not in self._transaction_rollback:
                self._transaction_rollback[name] = old_value
            self._transaction_changes[name] = value
        else:
            self._values[name] = value
        
        # Track change in history
        if self._enable_history and self._history is not None:
            import time
            if name not in self._history:
                self._history[name] = []
            self._history[name].append((old_value, value, time.time()))
            
            # Limit history size
            if len(self._history[name]) > 100:  # Keep last 100 changes
                self._history[name] = self._history[name][-100:]
        
        # Trigger callbacks (not during transactions)
        if self._enable_callbacks and not self._in_transaction:
            self._trigger_change_callbacks(name, old_value, self.get(name))
        
        # Update dependent parameters
        self._update_dependents(name, value)
        
        # Clear computed lazy defaults for this parameter
        if name in self._computed_defaults:
            del self._computed_defaults[name]
    
    def reset(self, name: str, force: bool = False) -> None:
        """
        Reset parameter to default value.
        
        Args:
            name: Parameter name
            force: Whether to override locked parameters
        """
        if not force and name in self._locked_params:
            raise ValueError(f"Parameter '{name}' is locked and cannot be reset")
        
        if name in self._values:
            old_value = self._values[name]
            del self._values[name]
            
            # Track in history
            if self._enable_history and self._history is not None:
                import time
                if name not in self._history:
                    self._history[name] = []
                default_value = self.get(name)  # Get the default
                self._history[name].append((old_value, default_value, time.time()))
            
            # Trigger callbacks (not during transactions)
            if self._enable_callbacks and not self._in_transaction:
                self._trigger_change_callbacks(name, old_value, self.get(name))
        
        # Clear computed lazy defaults
        if name in self._computed_defaults:
            del self._computed_defaults[name]
    
    def update(self, values: Union[Dict[str, Any], 'ParameterManager'], 
               force: bool = False, validate_all: bool = True) -> None:
        """
        Enhanced batch update parameters with validation and transaction support.
        
        Args:
            values: Dictionary of values or another ParameterManager
            force: Whether to override locked parameters
            validate_all: Whether to validate all parameters before applying any
        """
        if isinstance(values, dict):
            update_dict = values
        elif isinstance(values, ParameterManager):
            update_dict = {name: value for name, value in values._values.items()
                         if name in self._descriptors}
        else:
            raise TypeError("Values must be dict or ParameterManager")
        
        # Pre-validation if requested
        if validate_all:
            validation_errors = []
            for name, value in update_dict.items():
                if name in self._descriptors:
                    if not force and name in self._locked_params:
                        validation_errors.append(f"Parameter '{name}' is locked")
                    else:
                        descriptor = self._descriptors[name]
                        if not descriptor.validate(value):
                            validation_errors.append(f"Invalid value for '{name}': {value}")
            
            if validation_errors:
                raise ValueError("Validation errors: " + "; ".join(validation_errors))
        
        # Apply updates
        for name, value in update_dict.items():
            if name in self._descriptors:
                self.set(name, value, force=force)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with all current values."""
        result = {}
        
        # Add defaults first
        for name, default in self._defaults.items():
            if name in self._lazy_defaults:
                if name not in self._computed_defaults:
                    self._computed_defaults[name] = self._lazy_defaults[name]()
                result[name] = self._computed_defaults[name]
            else:
                result[name] = default
        
        # Override with current values
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
        """Create a deep copy of this parameter manager."""
        new_manager = ParameterManager(
            self._descriptors, 
            enable_history=self._enable_history,
            enable_callbacks=self._enable_callbacks
        )
        new_manager._values = self._values.copy()
        new_manager._locked_params = self._locked_params.copy()
        new_manager._groups = {k: v.copy() for k, v in self._groups.items()}
        new_manager._param_groups = self._param_groups.copy()
        return new_manager
    
    # ========================
    # Enhanced Inheritance System
    # ========================
    
    def inherit_from(self, parent: 'ParameterManager', 
                     strategy: str = 'merge', 
                     conflict_resolution: str = 'parent',
                     selective: Optional[List[str]] = None) -> None:
        """
        Enhanced inheritance with conflict resolution and selective inheritance.
        
        Args:
            parent: Parent parameter manager
            strategy: 'merge', 'replace', or 'selective'
            conflict_resolution: 'parent', 'child', or 'raise'
            selective: List of parameter names to inherit (for selective strategy)
        """
        if strategy == 'selective':
            param_names = selective or []
        else:
            param_names = [name for name in parent._values.keys() 
                          if name in self._descriptors]
        
        conflicts = []
        
        for name in param_names:
            if name in self._descriptors:
                parent_value = parent.get(name)
                has_current_value = name in self._values
                
                if has_current_value and strategy == 'merge':
                    # Handle conflicts
                    if conflict_resolution == 'parent':
                        self._values[name] = parent_value
                        self._inherited_params[name] = parent
                    elif conflict_resolution == 'child':
                        # Keep current value
                        pass
                    elif conflict_resolution == 'raise':
                        conflicts.append(name)
                    else:
                        raise ValueError(f"Unknown conflict resolution: {conflict_resolution}")
                else:
                    # No conflict or replace strategy
                    if not has_current_value or strategy == 'replace':
                        self._values[name] = parent_value
                        self._inherited_params[name] = parent
        
        if conflicts:
            raise ValueError(f"Parameter conflicts: {conflicts}")
        
        # Track inheritance chain
        if parent not in self._inheritance_chain:
            self._inheritance_chain.append(parent)
    
    def get_inheritance_info(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get inheritance information for a parameter.
        
        Args:
            name: Parameter name
            
        Returns:
            Dictionary with inheritance info or None
        """
        if name in self._inherited_params:
            source = self._inherited_params[name]
            return {
                'inherited': True,
                'source': source,
                'chain_position': self._inheritance_chain.index(source) if source in self._inheritance_chain else -1
            }
        return None
    
    # ========================
    # Parameter Locking
    # ========================
    
    def lock_parameter(self, name: str) -> None:
        """Lock a parameter to prevent modification."""
        if name in self._descriptors:
            self._locked_params.add(name)
        else:
            raise AttributeError(f"Unknown parameter: {name}")
    
    def unlock_parameter(self, name: str) -> None:
        """Unlock a parameter to allow modification."""
        self._locked_params.discard(name)
    
    def is_locked(self, name: str) -> bool:
        """Check if a parameter is locked."""
        return name in self._locked_params
    
    def get_locked_parameters(self) -> List[str]:
        """Get list of all locked parameters."""
        return list(self._locked_params)
    
    # ========================
    # Parameter Groups
    # ========================
    
    def create_group(self, group_name: str, param_names: List[str]) -> None:
        """
        Create a parameter group.
        
        Args:
            group_name: Name of the group
            param_names: List of parameter names in the group
        """
        # Validate parameter names
        invalid_params = [name for name in param_names if name not in self._descriptors]
        if invalid_params:
            raise AttributeError(f"Unknown parameters: {invalid_params}")
        
        self._groups[group_name] = param_names.copy()
        for name in param_names:
            self._param_groups[name] = group_name
    
    def get_group(self, group_name: str) -> List[str]:
        """Get parameter names in a group."""
        return self._groups.get(group_name, []).copy()
    
    def get_parameter_group(self, param_name: str) -> Optional[str]:
        """Get the group name for a parameter."""
        return self._param_groups.get(param_name)
    
    def set_group(self, group_name: str, values: Dict[str, Any]) -> None:
        """Set values for all parameters in a group."""
        if group_name not in self._groups:
            raise ValueError(f"Unknown group: {group_name}")
        
        group_params = self._groups[group_name]
        group_values = {name: values[name] for name in group_params if name in values}
        self.update(group_values)
    
    def get_group_values(self, group_name: str) -> Dict[str, Any]:
        """Get values for all parameters in a group."""
        if group_name not in self._groups:
            raise ValueError(f"Unknown group: {group_name}")
        
        return {name: self.get(name) for name in self._groups[group_name]}
    
    # ========================
    # Lazy Defaults
    # ========================
    
    def set_lazy_default(self, name: str, lazy_func: Callable[[], Any]) -> None:
        """
        Set a lazy default value function for a parameter.
        
        Args:
            name: Parameter name
            lazy_func: Function that returns the default value when called
        """
        if name not in self._descriptors:
            raise AttributeError(f"Unknown parameter: {name}")
        
        self._lazy_defaults[name] = lazy_func
        # Clear any previously computed value
        if name in self._computed_defaults:
            del self._computed_defaults[name]
    
    def clear_lazy_default(self, name: str) -> None:
        """Clear lazy default for a parameter."""
        if name in self._lazy_defaults:
            del self._lazy_defaults[name]
        if name in self._computed_defaults:
            del self._computed_defaults[name]
    
    # ========================
    # Change Tracking and Callbacks
    # ========================
    
    def add_change_callback(self, callback: Callable[[str, Any, Any], None], 
                           param_name: Optional[str] = None) -> None:
        """
        Add a callback for parameter changes.
        
        Args:
            callback: Function called with (param_name, old_value, new_value)
            param_name: Specific parameter to watch, or None for all parameters
        """
        if not self._enable_callbacks:
            return
        
        if param_name is None:
            self._global_callbacks.append(callback)
        else:
            if param_name not in self._change_callbacks:
                self._change_callbacks[param_name] = []
            self._change_callbacks[param_name].append(callback)
    
    def remove_change_callback(self, callback: Callable[[str, Any, Any], None],
                              param_name: Optional[str] = None) -> None:
        """Remove a change callback."""
        if not self._enable_callbacks:
            return
        
        if param_name is None:
            if callback in self._global_callbacks:
                self._global_callbacks.remove(callback)
        else:
            if param_name in self._change_callbacks:
                if callback in self._change_callbacks[param_name]:
                    self._change_callbacks[param_name].remove(callback)
    
    def _trigger_change_callbacks(self, name: str, old_value: Any, new_value: Any) -> None:
        """Trigger change callbacks for a parameter."""
        if not self._enable_callbacks:
            return
        
        # Parameter-specific callbacks
        if name in self._change_callbacks:
            for callback in self._change_callbacks[name]:
                try:
                    callback(name, old_value, new_value)
                except Exception as e:
                    # Log error but don't let callback errors break parameter setting
                    print(f"Warning: Callback error for parameter '{name}': {e}")
        
        # Global callbacks
        for callback in self._global_callbacks:
            try:
                callback(name, old_value, new_value)
            except Exception as e:
                print(f"Warning: Global callback error for parameter '{name}': {e}")
    
    def get_change_history(self, name: str, limit: Optional[int] = None) -> List[tuple]:
        """
        Get change history for a parameter.
        
        Args:
            name: Parameter name
            limit: Maximum number of changes to return (most recent first)
            
        Returns:
            List of (old_value, new_value, timestamp) tuples
        """
        if not self._enable_history or self._history is None:
            return []
        
        history = self._history.get(name, [])
        if limit is not None:
            history = history[-limit:]
        
        return history.copy()
    
    def clear_history(self, name: Optional[str] = None) -> None:
        """Clear change history for a parameter or all parameters."""
        if not self._enable_history or self._history is None:
            return
        
        if name is None:
            self._history.clear()
        elif name in self._history:
            del self._history[name]
    
    # ========================
    # Dependencies
    # ========================
    
    def add_dependency(self, param_name: str, dependent_param: str) -> None:
        """
        Add a dependency relationship between parameters.
        
        Args:
            param_name: Parameter that others depend on
            dependent_param: Parameter that depends on param_name
        """
        if param_name not in self._descriptors:
            raise AttributeError(f"Unknown parameter: {param_name}")
        if dependent_param not in self._descriptors:
            raise AttributeError(f"Unknown parameter: {dependent_param}")
        
        if param_name not in self._dependencies:
            self._dependencies[param_name] = []
        if dependent_param not in self._dependencies[param_name]:
            self._dependencies[param_name].append(dependent_param)
        
        if dependent_param not in self._dependents:
            self._dependents[dependent_param] = []
        if param_name not in self._dependents[dependent_param]:
            self._dependents[dependent_param].append(param_name)
    
    def remove_dependency(self, param_name: str, dependent_param: str) -> None:
        """Remove a dependency relationship."""
        if param_name in self._dependencies:
            if dependent_param in self._dependencies[param_name]:
                self._dependencies[param_name].remove(dependent_param)
        
        if dependent_param in self._dependents:
            if param_name in self._dependents[dependent_param]:
                self._dependents[dependent_param].remove(param_name)
    
    def get_dependencies(self, param_name: str) -> List[str]:
        """Get list of parameters that depend on the given parameter."""
        return self._dependencies.get(param_name, []).copy()
    
    def get_dependents(self, param_name: str) -> List[str]:
        """Get list of parameters that the given parameter depends on."""
        return self._dependents.get(param_name, []).copy()
    
    def _update_dependents(self, param_name: str, new_value: Any) -> None:
        """Update dependent parameters when a parameter changes."""
        # This is a placeholder for dependency update logic
        # In a real implementation, you might want to trigger recalculation
        # of dependent parameters or notify them of changes
        pass
    
    # ========================
    # Transaction Support
    # ========================
    
    def begin_transaction(self) -> None:
        """Begin a parameter transaction."""
        if self._in_transaction:
            raise RuntimeError("Already in a transaction")
        
        self._in_transaction = True
        self._transaction_changes.clear()
        self._transaction_rollback.clear()
    
    def commit_transaction(self) -> None:
        """Commit the current transaction."""
        if not self._in_transaction:
            raise RuntimeError("Not in a transaction")
        
        # Apply all changes
        self._values.update(self._transaction_changes)
        
        # Trigger callbacks for all changes
        if self._enable_callbacks:
            for name, new_value in self._transaction_changes.items():
                old_value = self._transaction_rollback.get(name, self.get(name))
                self._trigger_change_callbacks(name, old_value, new_value)
        
        self._in_transaction = False
        self._transaction_changes.clear()
        self._transaction_rollback.clear()
    
    def rollback_transaction(self) -> None:
        """Rollback the current transaction."""
        if not self._in_transaction:
            raise RuntimeError("Not in a transaction")
        
        self._in_transaction = False
        self._transaction_changes.clear()
        self._transaction_rollback.clear()
    
    def is_in_transaction(self) -> bool:
        """Check if currently in a transaction."""
        return self._in_transaction


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


class HybridParameterMeta(type):
    """
    Hybrid metaclass for temporary integration with MetaParams.
    
    This metaclass bridges the gap between the new descriptor-based parameter 
    system and the existing MetaParams system during the transition period.
    It provides compatibility with both systems while gradually migrating
    to the new approach.
    """
    
    def __new__(mcs, name, bases, namespace, **kwargs):
        """Create a new class with hybrid parameter support."""
        # Check if any base classes use MetaParams
        has_metaparams_base = False
        metaparams_bases = []
        
        for base in bases:
            if hasattr(base, 'params') and hasattr(base.params, '_getitems'):
                has_metaparams_base = True
                metaparams_bases.append(base)
        
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
        
        # Handle legacy params definition
        if 'params' in namespace and isinstance(namespace['params'], (tuple, list)):
            legacy_params = namespace.pop('params')
            for param_def in legacy_params:
                if isinstance(param_def, (tuple, list)) and len(param_def) >= 2:
                    param_name, param_default = param_def[0], param_def[1]
                    if param_name not in all_descriptors:
                        all_descriptors[param_name] = ParameterDescriptor(
                            default=param_default, 
                            name=param_name
                        )
        
        # Store collected descriptors in the namespace
        namespace['_parameter_descriptors'] = all_descriptors
        
        # Store information about MetaParams compatibility
        namespace['_has_metaparams_heritage'] = has_metaparams_base
        namespace['_metaparams_bases'] = metaparams_bases
        
        # Create the class
        cls = super().__new__(mcs, name, bases, namespace)
        
        return cls


class ParameterizedMeta(HybridParameterMeta):
    """
    Enhanced metaclass for parameterized classes.
    
    This metaclass extends HybridParameterMeta to provide full parameter
    descriptor collection and validation during class creation.
    """
    pass


class ParameterizedBase(metaclass=ParameterizedMeta):
    """
    Enhanced base class for objects with parameters.
    
    This class provides the modern parameter system interface while maintaining
    backward compatibility with the old MetaParams-based system. It automatically
    handles parameter initialization, validation, and access with enhanced error
    handling and temporary MetaParams integration.
    
    Day 34-35 Enhancements:
    - Temporary MetaParams integration for seamless migration
    - Enhanced error handling and validation
    - Improved backward compatibility interfaces
    - Parameter inheritance from MetaParams-based classes
    """
    
    def __init__(self, **kwargs):
        """
        Initialize parameterized object with enhanced error handling.
        
        Args:
            **kwargs: Keyword arguments including parameter values
        """
        try:
            # Initialize parameter manager
            descriptors = getattr(self.__class__, '_parameter_descriptors', {})
            
            # Check for MetaParams heritage and handle compatibility
            if getattr(self.__class__, '_has_metaparams_heritage', False):
                self._init_with_metaparams_compatibility(descriptors, kwargs)
            else:
                self._init_with_new_system(descriptors, kwargs)
            
            # Enhanced error handling for parameter validation
            validation_errors = self.validate_params()
            if validation_errors:
                error_msg = "Parameter validation failed:\n" + "\n".join(f"  - {err}" for err in validation_errors)
                raise ValueError(error_msg)
                
        except Exception as e:
            self._handle_initialization_error(e)
            raise
    
    def _init_with_metaparams_compatibility(self, descriptors: Dict[str, ParameterDescriptor], kwargs: Dict[str, Any]):
        """
        Initialize with MetaParams compatibility mode.
        
        Args:
            descriptors: Parameter descriptors
            kwargs: Initialization keyword arguments
        """
        # Initialize the new parameter manager
        self._param_manager = ParameterManager(
            descriptors, 
            enable_history=True, 
            enable_callbacks=True
        )
        
        # Handle inheritance from MetaParams-based classes
        metaparams_bases = getattr(self.__class__, '_metaparams_bases', [])
        for base in metaparams_bases:
            if hasattr(base, 'params') and hasattr(base.params, '_getitems'):
                # Extract parameters from MetaParams base
                for param_name, param_default in base.params._getitems():
                    if param_name not in descriptors:
                        # Create a descriptor for the MetaParams parameter
                        descriptors[param_name] = ParameterDescriptor(
                            default=param_default,
                            name=param_name
                        )
                        self._param_manager._descriptors[param_name] = descriptors[param_name]
                        self._param_manager._defaults[param_name] = param_default
        
        # Separate parameter kwargs from other kwargs
        param_kwargs = {}
        other_kwargs = {}
        
        for key, value in kwargs.items():
            if key in descriptors or key in self._param_manager._descriptors:
                param_kwargs[key] = value
            else:
                other_kwargs[key] = value
        
        # Set parameter values with enhanced validation
        if param_kwargs:
            try:
                self._param_manager.update(param_kwargs)
            except Exception as e:
                raise ValueError(f"Failed to set parameters {list(param_kwargs.keys())}: {e}")
        
        # Create backward compatibility accessors
        self.params = ParameterAccessor(self._param_manager)
        self.p = self.params  # Short alias
        
        # Call parent __init__ with remaining kwargs
        super().__init__(**other_kwargs)
    
    def _init_with_new_system(self, descriptors: Dict[str, ParameterDescriptor], kwargs: Dict[str, Any]):
        """
        Initialize with the new parameter system only.
        
        Args:
            descriptors: Parameter descriptors
            kwargs: Initialization keyword arguments
        """
        self._param_manager = ParameterManager(
            descriptors,
            enable_history=True,
            enable_callbacks=True
        )
        
        # Separate parameter kwargs from other kwargs
        param_kwargs = {}
        other_kwargs = {}
        
        for key, value in kwargs.items():
            if key in descriptors:
                param_kwargs[key] = value
            else:
                other_kwargs[key] = value
        
        # Set parameter values with validation
        if param_kwargs:
            try:
                self._param_manager.update(param_kwargs)
            except Exception as e:
                raise ValueError(f"Failed to set parameters {list(param_kwargs.keys())}: {e}")
        
        # Create backward compatibility accessors
        self.params = ParameterAccessor(self._param_manager)
        self.p = self.params  # Short alias
        
        # Call parent __init__ with remaining kwargs
        super().__init__(**other_kwargs)
    
    def _handle_initialization_error(self, error: Exception):
        """
        Handle initialization errors with enhanced debugging information.
        
        Args:
            error: The exception that occurred
        """
        error_context = {
            'class_name': self.__class__.__name__,
            'module': self.__class__.__module__,
            'has_metaparams_heritage': getattr(self.__class__, '_has_metaparams_heritage', False),
            'parameter_count': len(getattr(self.__class__, '_parameter_descriptors', {})),
            'error_type': type(error).__name__,
            'error_message': str(error)
        }
        
        # Log detailed error information (in production, this would use proper logging)
        print(f"ParameterizedBase initialization error context: {error_context}")
        
        # Add additional context to certain error types
        if isinstance(error, (TypeError, ValueError)):
            # Enhance the error message with parameter information
            param_info = self.get_param_info() if hasattr(self, '_param_manager') else {}
            error.args = (f"{error}. Available parameters: {list(param_info.keys())}",)
    
    def get_param(self, name: str, default: Any = None) -> Any:
        """
        Get parameter value with enhanced error handling.
        
        Args:
            name: Parameter name
            default: Default value if parameter not found
            
        Returns:
            Parameter value
            
        Raises:
            AttributeError: If parameter doesn't exist and no default provided
        """
        try:
            return self._param_manager.get(name, default)
        except AttributeError:
            if default is None:
                available_params = list(self._param_manager.keys()) if hasattr(self, '_param_manager') else []
                raise AttributeError(
                    f"Parameter '{name}' not found in {self.__class__.__name__}. "
                    f"Available parameters: {available_params}"
                )
            return default
    
    def set_param(self, name: str, value: Any, validate: bool = True) -> None:
        """
        Set parameter value with enhanced validation.
        
        Args:
            name: Parameter name
            value: Parameter value
            validate: Whether to validate the value before setting
            
        Raises:
            AttributeError: If parameter doesn't exist
            ValueError: If validation fails
            TypeError: If type conversion fails
        """
        try:
            if validate:
                # Pre-validate the value
                descriptors = getattr(self.__class__, '_parameter_descriptors', {})
                if name in descriptors:
                    descriptor = descriptors[name]
                    if not descriptor.validate(value):
                        raise ValueError(
                            f"Validation failed for parameter '{name}' with value {value}. "
                            f"Expected type: {descriptor.type_}, Required: {descriptor.required}"
                        )
            
            self._param_manager.set(name, value)
        except AttributeError:
            available_params = list(self._param_manager.keys()) if hasattr(self, '_param_manager') else []
            raise AttributeError(
                f"Cannot set unknown parameter '{name}' in {self.__class__.__name__}. "
                f"Available parameters: {available_params}"
            )
    
    def get_param_info(self) -> Dict[str, Dict[str, Any]]:
        """
        Get comprehensive information about all parameters.
        
        Returns:
            Dictionary mapping parameter names to their detailed information
        """
        descriptors = getattr(self.__class__, '_parameter_descriptors', {})
        param_info = {}
        
        for name, desc in descriptors.items():
            try:
                current_value = self._param_manager.get(name) if hasattr(self, '_param_manager') else desc.default
                type_info = desc.get_type_info()
                type_info.update({
                    'current_value': current_value,
                    'is_default': current_value == desc.default,
                    'source': 'new_system'
                })
                param_info[name] = type_info
            except Exception as e:
                # Ensure we don't fail if parameter access fails
                param_info[name] = {
                    'name': name,
                    'error': str(e),
                    'source': 'error'
                }
        
        return param_info
    
    def validate_params(self) -> List[str]:
        """
        Validate all current parameter values with enhanced reporting.
        
        Returns:
            List of validation error messages (empty if all valid)
        """
        errors = []
        descriptors = getattr(self.__class__, '_parameter_descriptors', {})
        
        for name, descriptor in descriptors.items():
            try:
                current_value = self._param_manager.get(name) if hasattr(self, '_param_manager') else descriptor.default
                
                # Check required parameters
                if descriptor.required and current_value is None:
                    errors.append(f"Required parameter '{name}' is missing or None")
                    continue
                
                # Validate current value
                if not descriptor.validate(current_value):
                    type_info = f" (expected: {descriptor.type_.__name__})" if descriptor.type_ else ""
                    errors.append(f"Parameter '{name}' has invalid value: {current_value}{type_info}")
                    
            except Exception as e:
                errors.append(f"Failed to validate parameter '{name}': {e}")
        
        return errors
    
    def reset_param(self, name: str) -> None:
        """
        Reset parameter to its default value.
        
        Args:
            name: Parameter name
            
        Raises:
            AttributeError: If parameter doesn't exist
        """
        try:
            self._param_manager.reset(name)
        except AttributeError:
            available_params = list(self._param_manager.keys()) if hasattr(self, '_param_manager') else []
            raise AttributeError(
                f"Cannot reset unknown parameter '{name}' in {self.__class__.__name__}. "
                f"Available parameters: {available_params}"
            )
    
    def reset_all_params(self) -> None:
        """Reset all parameters to their default values."""
        if hasattr(self, '_param_manager'):
            for name in list(self._param_manager.keys()):
                try:
                    self._param_manager.reset(name)
                except Exception as e:
                    warnings.warn(f"Failed to reset parameter '{name}': {e}")
    
    def get_modified_params(self) -> Dict[str, Any]:
        """
        Get only parameters that have been modified from their defaults.
        
        Returns:
            Dictionary of modified parameters and their values
        """
        modified = {}
        descriptors = getattr(self.__class__, '_parameter_descriptors', {})
        
        for name, descriptor in descriptors.items():
            try:
                current_value = self._param_manager.get(name) if hasattr(self, '_param_manager') else descriptor.default
                if current_value != descriptor.default:
                    modified[name] = current_value
            except Exception:
                # Skip parameters that can't be accessed
                continue
        
        return modified
    
    def copy_params_from(self, other: 'ParameterizedBase', 
                         param_names: Optional[List[str]] = None,
                         exclude: Optional[List[str]] = None) -> None:
        """
        Copy parameters from another ParameterizedBase instance.
        
        Args:
            other: Source object to copy parameters from
            param_names: Specific parameter names to copy (None for all)
            exclude: Parameter names to exclude from copying
            
        Raises:
            TypeError: If other is not a ParameterizedBase instance
            ValueError: If parameter copying fails
        """
        if not isinstance(other, ParameterizedBase):
            raise TypeError(f"Can only copy parameters from ParameterizedBase instances, got {type(other)}")
        
        try:
            if not hasattr(other, '_param_manager'):
                warnings.warn(f"Source object {other.__class__.__name__} has no parameter manager")
                return
            
            # Determine which parameters to copy
            if param_names is None:
                param_names = list(other._param_manager.keys())
            
            if exclude:
                param_names = [name for name in param_names if name not in exclude]
            
            # Copy parameters
            copied_count = 0
            for name in param_names:
                if name in self._param_manager._descriptors:
                    try:
                        value = other._param_manager.get(name)
                        self._param_manager.set(name, value)
                        copied_count += 1
                    except Exception as e:
                        warnings.warn(f"Failed to copy parameter '{name}': {e}")
            
            print(f"Copied {copied_count} parameters from {other.__class__.__name__}")
            
        except Exception as e:
            raise ValueError(f"Failed to copy parameters: {e}")
    
    def __repr__(self) -> str:
        """Enhanced string representation including parameter information."""
        class_name = self.__class__.__name__
        param_count = len(getattr(self.__class__, '_parameter_descriptors', {}))
        modified_count = len(self.get_modified_params()) if hasattr(self, '_param_manager') else 0
        
        return f"{class_name}(params={param_count}, modified={modified_count})"


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
        if value is None:
            return True
        # Only accept int and float types, not strings
        if not isinstance(value, (int, float)):
            return False
        
        float_value = float(value)
        if min_val is not None and float_value < min_val:
            return False
        if max_val is not None and float_value > max_val:
            return False
        return True
    return validator


def FloatParam(default=None, min_val: Optional[float] = None, max_val: Optional[float] = None, doc: str = None) -> ParameterDescriptor:
    """
    Create a Float parameter descriptor with optional range validation.
    
    Args:
        default: Default value
        min_val: Minimum allowed value  
        max_val: Maximum allowed value
        doc: Parameter documentation
        
    Returns:
        ParameterDescriptor with float type and validation
    """
    validator = Float(min_val=min_val, max_val=max_val) if (min_val is not None or max_val is not None) else None
    return ParameterDescriptor(default=default, type_=float, validator=validator, doc=doc)


def BoolParam(default=None, doc: str = None) -> ParameterDescriptor:
    """
    Create a Boolean parameter descriptor.
    
    Args:
        default: Default value
        doc: Parameter documentation
        
    Returns:
        ParameterDescriptor with bool type
    """
    def validator(value):
        if value is None:
            return True
        return isinstance(value, bool) or value in (0, 1, 'True', 'False', 'true', 'false')
    
    return ParameterDescriptor(default=default, type_=bool, validator=validator, doc=doc)


def StringParam(default=None, min_length: Optional[int] = None, max_length: Optional[int] = None, doc: str = None) -> ParameterDescriptor:
    """
    Create a String parameter descriptor with optional length validation.
    
    Args:
        default: Default value
        min_length: Minimum string length
        max_length: Maximum string length
        doc: Parameter documentation
        
    Returns:
        ParameterDescriptor with string type and validation
    """
    validator = String(min_length=min_length, max_length=max_length) if (min_length is not None or max_length is not None) else None
    return ParameterDescriptor(default=default, type_=str, validator=validator, doc=doc)


def String(min_length: Optional[int] = None, max_length: Optional[int] = None) -> Callable[[Any], bool]:
    """
    Create a validator for string parameters with optional length validation.
    
    Args:
        min_length: Minimum string length
        max_length: Maximum string length
        
    Returns:
        Validator function
    """
    def validator(value):
        if value is None:
            return True
        # Only accept string types, no conversion
        if not isinstance(value, str):
            return False
        if min_length is not None and len(value) < min_length:
            return False
        if max_length is not None and len(value) > max_length:
            return False
        return True
    return validator


def Bool() -> Callable[[Any], bool]:
    """
    Create a validator for boolean parameters.
    
    Returns:
        Validator function
    """
    def validator(value):
        if value is None:
            return True
        return isinstance(value, bool) or value in (0, 1, 'True', 'False', 'true', 'false')
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


class MetaParamsBridge:
    """
    Bridge class for transitioning from MetaParams to new parameter system.
    
    This class provides utilities for converting between the old MetaParams
    system and the new descriptor-based system during the migration period.
    """
    
    @staticmethod
    def extract_params_from_metaparams_class(cls) -> Dict[str, ParameterDescriptor]:
        """
        Extract parameter descriptors from a MetaParams-based class.
        
        Args:
            cls: Class with MetaParams-based parameters
            
        Returns:
            Dictionary of parameter descriptors
        """
        descriptors = {}
        
        if hasattr(cls, 'params') and hasattr(cls.params, '_getitems'):
            for param_name, param_default in cls.params._getitems():
                descriptors[param_name] = ParameterDescriptor(
                    default=param_default,
                    name=param_name,
                    doc=f"Migrated from MetaParams class {cls.__name__}"
                )
        
        return descriptors
    
    @staticmethod 
    def convert_legacy_params_tuple(params_tuple) -> Dict[str, ParameterDescriptor]:
        """
        Convert legacy params tuple to parameter descriptors.
        
        Args:
            params_tuple: Legacy params tuple like (('param1', 10), ('param2', 'value'))
            
        Returns:
            Dictionary of parameter descriptors
        """
        descriptors = {}
        
        if isinstance(params_tuple, (tuple, list)):
            for param_def in params_tuple:
                if isinstance(param_def, (tuple, list)) and len(param_def) >= 2:
                    param_name, param_default = param_def[0], param_def[1]
                    
                    # Try to infer type from default value
                    param_type = type(param_default) if param_default is not None else None
                    
                    descriptors[param_name] = ParameterDescriptor(
                        default=param_default,
                        type_=param_type,
                        name=param_name,
                        doc=f"Converted from legacy params tuple"
                    )
        
        return descriptors
    
    @staticmethod
    def create_compatibility_wrapper(metaparams_class):
        """
        Create a compatibility wrapper for MetaParams-based classes.
        
        Args:
            metaparams_class: Original MetaParams-based class
            
        Returns:
            New class that uses the modern parameter system
        """
        # Extract existing parameters
        descriptors = MetaParamsBridge.extract_params_from_metaparams_class(metaparams_class)
        
        # Create new class with descriptor-based parameters
        class_name = f"Modern{metaparams_class.__name__}"
        
        # Build class namespace
        namespace = {
            '__module__': metaparams_class.__module__,
            '__doc__': f"Modernized version of {metaparams_class.__name__} with descriptor-based parameters",
        }
        
        # Add parameter descriptors to namespace
        for name, descriptor in descriptors.items():
            namespace[name] = descriptor
        
        # Create the new class
        new_class = ParameterizedMeta(
            class_name,
            (ParameterizedBase,),
            namespace
        )
        
        return new_class


class ParameterValidationError(ValueError):
    """Specific exception for parameter validation errors."""
    
    def __init__(self, parameter_name: str, value: Any, expected_type: Optional[Type] = None, 
                 additional_info: str = ""):
        self.parameter_name = parameter_name
        self.value = value
        self.expected_type = expected_type
        
        message = f"Validation failed for parameter '{parameter_name}' with value {value}"
        if expected_type:
            message += f" (expected type: {expected_type.__name__})"
        if additional_info:
            message += f". {additional_info}"
            
        super().__init__(message)


class ParameterAccessError(AttributeError):
    """Specific exception for parameter access errors."""
    
    def __init__(self, parameter_name: str, class_name: str, available_params: List[str]):
        self.parameter_name = parameter_name
        self.class_name = class_name
        self.available_params = available_params
        
        message = f"Parameter '{parameter_name}' not found in {class_name}"
        if available_params:
            message += f". Available parameters: {available_params}"
        else:
            message += ". No parameters are available"
            
        super().__init__(message)


def validate_parameter_compatibility(old_class, new_class) -> Dict[str, Any]:
    """
    Validate compatibility between old MetaParams class and new descriptor-based class.
    
    Args:
        old_class: Original MetaParams-based class
        new_class: New descriptor-based class
        
    Returns:
        Dictionary with compatibility analysis results
    """
    results = {
        'compatible': True,
        'missing_params': [],
        'extra_params': [],
        'type_mismatches': [],
        'default_mismatches': []
    }
    
    # Get old parameters
    old_params = {}
    if hasattr(old_class, 'params') and hasattr(old_class.params, '_getitems'):
        old_params = dict(old_class.params._getitems())
    
    # Get new parameters  
    new_params = {}
    if hasattr(new_class, '_parameter_descriptors'):
        new_params = {name: desc.default for name, desc in new_class._parameter_descriptors.items()}
    
    # Check for missing parameters
    for name in old_params:
        if name not in new_params:
            results['missing_params'].append(name)
            results['compatible'] = False
    
    # Check for extra parameters
    for name in new_params:
        if name not in old_params:
            results['extra_params'].append(name)
    
    # Check for default value mismatches
    for name in old_params:
        if name in new_params:
            if old_params[name] != new_params[name]:
                results['default_mismatches'].append({
                    'param': name,
                    'old_default': old_params[name],
                    'new_default': new_params[name]
                })
    
    return results 