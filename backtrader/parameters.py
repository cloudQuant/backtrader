"""
New Parameter System for Backtrader

This module implements a modern parameter system that replaces the metaclass-based
parameter handling with descriptor-based approach. This provides better type safety,
validation, and maintainability while maintaining backward compatibility.

Key Components:
- ParameterDescriptor: Core descriptor for parameter handling
- ParameterManager: Parameter storage and management
- ParameterizedBase: Base class for parameterized objects (without metaclass)
- Type checking and validation mechanisms
- Python 3.6+ __set_name__ support
"""

from typing import Any, Callable, Dict, List, Optional, Type, Union

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

    def __init__(
        self,
        default: Any = None,
        type_: Optional[Type] = None,
        validator: Optional[Callable[[Any], bool]] = None,
        doc: Optional[str] = None,
        name: Optional[str] = None,
        required: bool = False,
    ):
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
        self._attr_name = f"_param_{name}"

        # Don't register with owner._parameter_descriptors here since we use lazy loading
        # The _compute_parameter_descriptors method will find this descriptor later

    def __get__(self, obj, objtype=None):
        """Get parameter value from object instance."""
        if obj is None:
            return self

        # Get value from parameter manager
        if hasattr(obj, "_param_manager"):
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
        if hasattr(obj, "_param_manager"):
            obj._param_manager.set(self.name, value)
        else:
            # Fallback: set as object attribute
            setattr(obj, self._attr_name, value)

    def __delete__(self, obj):
        """Delete parameter value, reverting to default."""
        if hasattr(obj, "_param_manager"):
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
                if self.type_ is float:
                    # For float, accept int, float, and convertible strings
                    if not isinstance(value, (int, float)):
                        try:
                            float(value)  # Test conversion
                        except (ValueError, TypeError):
                            return False
                elif self.type_ is int:
                    # For int, accept int and convertible values
                    if not isinstance(value, int):
                        try:
                            int(value)  # Test conversion
                        except (ValueError, TypeError):
                            return False
                elif self.type_ is bool:
                    # For bool, be flexible with boolean-like values
                    if not isinstance(value, bool) and value not in (
                        0,
                        1,
                        "True",
                        "False",
                        "true",
                        "false",
                    ):
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
            "name": self.name,
            "type": self.type_,
            "default": self.default,
            "required": self.required,
            "has_validator": self.validator is not None,
            "doc": self.doc,
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
    """

    def __init__(
        self,
        descriptors: Dict[str, ParameterDescriptor],
        initial_values: Optional[Dict[str, Any]] = None,
        enable_history: bool = True,
        enable_callbacks: bool = True,
    ):
        """
        Initialize parameter manager.

        Args:
            descriptors: Dictionary of parameter descriptors
            initial_values: Initial parameter values
            enable_history: Whether to track parameter change history
            enable_callbacks: Whether to enable change callbacks
        """
        self._descriptors = descriptors.copy()
        self._values = {}
        self._defaults = {}
        self._modified = set()

        # Extract defaults from descriptors
        for name, desc in descriptors.items():
            self._defaults[name] = desc.default

        # Advanced features
        self._enable_history = enable_history
        self._enable_callbacks = enable_callbacks

        # Change tracking
        self._change_history = {} if enable_history else None
        self._change_callbacks = {} if enable_callbacks else None
        self._global_callbacks = [] if enable_callbacks else None

        # Parameter locking
        self._locked_params = set()

        # Parameter groups
        self._param_groups = {}
        self._param_to_group = {}

        # Lazy defaults
        self._lazy_defaults = {}

        # Dependencies
        self._dependencies = {}  # param -> list of dependents
        self._dependents = {}  # dependent -> list of params it depends on

        # Transaction support
        self._in_transaction = False
        self._transaction_snapshot = None

        # Value cache for lazy evaluation
        self._value_cache = {}
        self._cache_valid = set()

        # Inheritance tracking
        self._inheritance_sources = {}  # param -> source ParameterManager

        # Set initial values
        if initial_values:
            self.update(initial_values, validate_all=False)

    def _invalidate_cache(self, name: str) -> None:
        """Invalidate cache for a parameter."""
        self._cache_valid.discard(name)
        if name in self._value_cache:
            del self._value_cache[name]

    def _clear_cache(self) -> None:
        """Clear all cached values."""
        self._value_cache.clear()
        self._cache_valid.clear()

    def get(self, name: str, default: Any = None) -> Any:
        """
        Get parameter value with optimized caching and lazy evaluation support.

        Args:
            name: Parameter name
            default: Default value if parameter not found

        Returns:
            Parameter value
        """
        # Fast path: Check if we have a custom value (most common case)
        if name in self._values:
            return self._values[name]

        # Fast path: Check if we have a cached descriptor default
        if name in self._value_cache:
            return self._value_cache[name]

        # Check lazy defaults
        if name in self._lazy_defaults:
            if name not in self._cache_valid:
                try:
                    computed_value = self._lazy_defaults[name]()
                    self._value_cache[name] = computed_value
                    self._cache_valid.add(name)
                    return computed_value
                except Exception:
                    # If lazy evaluation fails, use descriptor default
                    if name in self._descriptors:
                        default_val = self._descriptors[name].default
                        self._value_cache[name] = default_val
                        return default_val
                    return default
            return self._value_cache[name]

        # Cache descriptor default for faster subsequent access
        if name in self._descriptors:
            default_val = self._descriptors[name].default
            self._value_cache[name] = default_val
            return default_val

        # Use provided default
        return default

    def set(
        self,
        name: str,
        value: Any,
        force: bool = False,
        trigger_callbacks: bool = True,
        skip_validation: bool = False,
    ) -> None:
        """
        Set parameter value with validation and dependency updates.

        Args:
            name: Parameter name
            value: Parameter value
            force: Force setting even if parameter is locked
            trigger_callbacks: Whether to trigger change callbacks
            skip_validation: Skip validation (use with caution)
        """
        # Check if parameter is locked
        if not force and name in self._locked_params:
            raise ValueError(f"Parameter '{name}' is locked and cannot be modified")

        # Get old value for callbacks and history
        old_value = self.get(name)

        # Validate if not skipping validation
        if not skip_validation and name in self._descriptors:
            descriptor = self._descriptors[name]
            if not descriptor.validate(value):
                raise ValueError(f"Invalid value for parameter '{name}': {value}")

        # Set the value
        self._values[name] = value
        self._modified.add(name)

        # Invalidate cache
        self._invalidate_cache(name)

        # Record change in history
        if self._enable_history and self._change_history is not None:
            if name not in self._change_history:
                self._change_history[name] = []

            import time

            self._change_history[name].append(
                {
                    "timestamp": time.time(),
                    "old_value": old_value,
                    "new_value": value,
                    "forced": force,
                }
            )

        # Trigger callbacks only if not in transaction
        if trigger_callbacks and self._enable_callbacks and not self._in_transaction:
            self._trigger_change_callbacks(name, old_value, value)

        # Update dependent parameters
        self._update_dependents(name, value)

    def reset(self, name: str, force: bool = False) -> None:
        """
        Reset parameter to its default value.

        Args:
            name: Parameter name
            force: Force reset even if parameter is locked
        """
        # Check if parameter is locked
        if not force and name in self._locked_params:
            raise ValueError(f"Parameter '{name}' is locked and cannot be reset")

        # Get old value for callbacks
        old_value = self.get(name)

        # Remove from values (will revert to default)
        if name in self._values:
            del self._values[name]

        # Remove from modified set
        self._modified.discard(name)

        # Invalidate cache
        self._invalidate_cache(name)

        # Get new value (should be default)
        new_value = self.get(name)

        # Record change in history
        if self._enable_history and self._change_history is not None:
            if name not in self._change_history:
                self._change_history[name] = []

            import time

            self._change_history[name].append(
                {
                    "timestamp": time.time(),
                    "old_value": old_value,
                    "new_value": new_value,
                    "reset": True,
                    "forced": force,
                }
            )

        # Trigger callbacks
        if self._enable_callbacks:
            self._trigger_change_callbacks(name, old_value, new_value)

    def update(
        self,
        values: Union[Dict[str, Any], "ParameterManager"],
        force: bool = False,
        validate_all: bool = True,
    ) -> None:
        """
        Update multiple parameters at once.

        Args:
            values: Dictionary of parameter values or another ParameterManager
            force: Force update even for locked parameters
            validate_all: Validate all parameters before updating any
        """
        if isinstance(values, ParameterManager):
            values = values.to_dict()

        # Validate all parameters first if requested
        if validate_all:
            validation_errors = []

            # Check for locked parameters
            for name, value in values.items():
                if not force and name in self._locked_params:
                    validation_errors.append(f"Parameter '{name}' is locked")

            # Check parameter validation
            for name, value in values.items():
                if name in self._descriptors:
                    descriptor = self._descriptors[name]
                    if not descriptor.validate(value):
                        validation_errors.append(f"Invalid value for '{name}': {value}")

            if validation_errors:
                raise ValueError("Validation errors: " + "; ".join(validation_errors))

        # Update parameters
        for name, value in values.items():
            self.set(name, value, force=force, skip_validation=not validate_all)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert parameter manager to dictionary.

        Returns:
            Dictionary of current parameter values
        """
        result = {}
        for name in self._descriptors:
            result[name] = self.get(name)
        return result

    def keys(self):
        """Get parameter names."""
        return self._descriptors.keys()

    def items(self):
        """Get parameter name-value pairs."""
        for name in self._descriptors:
            yield name, self.get(name)

    def values(self):
        """Get parameter values."""
        for name in self._descriptors:
            yield self.get(name)

    def __getitem__(self, name):
        return self.get(name)

    def __setitem__(self, name, value):
        self.set(name, value)

    def __contains__(self, name):
        return name in self._descriptors

    def __len__(self):
        return len(self._descriptors)

    def __iter__(self):
        return iter(self._descriptors)

    def copy(self) -> "ParameterManager":
        """
        Create a copy of this parameter manager.

        Returns:
            New ParameterManager instance with same values
        """
        new_manager = ParameterManager(
            self._descriptors,
            enable_history=self._enable_history,
            enable_callbacks=self._enable_callbacks,
        )

        # Copy current values
        new_manager._values = self._values.copy()
        new_manager._modified = self._modified.copy()

        # Copy advanced features
        if self._enable_history and self._change_history:
            new_manager._change_history = {k: v.copy() for k, v in self._change_history.items()}

        new_manager._locked_params = self._locked_params.copy()
        new_manager._param_groups = self._param_groups.copy()
        new_manager._param_to_group = self._param_to_group.copy()
        new_manager._lazy_defaults = self._lazy_defaults.copy()
        new_manager._dependencies = {k: v.copy() for k, v in self._dependencies.items()}
        new_manager._dependents = {k: v.copy() for k, v in self._dependents.items()}

        return new_manager

    def inherit_from(
        self,
        parent: "ParameterManager",
        strategy: str = "merge",
        conflict_resolution: str = "parent",
        selective: Optional[List[str]] = None,
    ) -> None:
        """
        Inherit parameters from another ParameterManager.

        Args:
            parent: Parent ParameterManager to inherit from
            strategy: Inheritance strategy ('merge', 'replace', 'add_only', 'selective')
            conflict_resolution: How to resolve conflicts ('parent', 'child', 'error', 'raise')
            selective: Only inherit specific parameters (list of names)
        """
        if strategy == "replace":
            # Replace all parameters
            if selective:
                for name in selective:
                    if name in parent._descriptors:
                        self._descriptors[name] = parent._descriptors[name]
                        self._defaults[name] = parent._defaults[name]
                        # Get the actual current value from parent
                        parent_value = parent.get(name)
                        self._values[name] = parent_value
                        self._inheritance_sources[name] = parent
            else:
                self._descriptors.update(parent._descriptors)
                self._defaults.update(parent._defaults)
                # Copy all current values from parent
                for name in parent._descriptors:
                    parent_value = parent.get(name)
                    self._values[name] = parent_value
                    self._inheritance_sources[name] = parent

        elif strategy == "merge":
            # Merge parameters, handling conflicts
            params_to_process = selective if selective else parent._descriptors.keys()

            for name in params_to_process:
                if name in parent._descriptors and name in self._descriptors:
                    # Only process parameters that exist in both parent and child
                    parent_value = parent.get(name)
                    parent_default = parent._defaults.get(name)

                    # Check if parent has actually set this parameter (has non-default value)
                    parent_has_value = parent_value != parent_default or name in parent._values

                    # Parameter exists in both parent and child
                    child_value = self.get(name)
                    child_default = self._defaults.get(name)
                    child_has_value = child_value != child_default or name in self._values

                    if parent_has_value and child_has_value:
                        # Both have values - this is a conflict
                        if conflict_resolution == "parent":
                            self._descriptors[name] = parent._descriptors[name]
                            self._defaults[name] = parent._defaults[name]
                            self._values[name] = parent_value
                            self._inheritance_sources[name] = parent
                        elif conflict_resolution == "child":
                            # Keep current values
                            pass
                        elif conflict_resolution in ("error", "raise"):
                            raise ValueError(
                                f"Parameter '{name}' conflicts between parent and child"
                            )
                    elif parent_has_value and not child_has_value:
                        # Parent has value, child has default - inherit from parent
                        self._descriptors[name] = parent._descriptors[name]
                        self._defaults[name] = parent._defaults[name]
                        self._values[name] = parent_value
                        self._inheritance_sources[name] = parent
                    # If only child has value, keep child's value

        elif strategy == "add_only":
            # Only add parameters that don't exist
            params_to_process = selective if selective else parent._descriptors.keys()

            for name in params_to_process:
                if name in parent._descriptors and name not in self._descriptors:
                    self._descriptors[name] = parent._descriptors[name]
                    self._defaults[name] = parent._defaults[name]
                    # Get the actual current value from parent
                    parent_value = parent.get(name)
                    self._values[name] = parent_value
                    self._inheritance_sources[name] = parent

        elif strategy == "selective":
            # Selective inheritance (same as merge with selective list)
            if not selective:
                raise ValueError("Selective strategy requires a list of parameter names")

            for name in selective:
                if name in parent._descriptors:
                    if name in self._descriptors:
                        # Handle conflicts based on conflict_resolution
                        if conflict_resolution == "parent":
                            self._descriptors[name] = parent._descriptors[name]
                            self._defaults[name] = parent._defaults[name]
                            # Get the actual current value from parent
                            parent_value = parent.get(name)
                            self._values[name] = parent_value
                            self._inheritance_sources[name] = parent
                        elif conflict_resolution == "child":
                            # Keep current values
                            pass
                        elif conflict_resolution in ("error", "raise"):
                            raise ValueError(
                                f"Parameter '{name}' conflicts between parent and child"
                            )
                    else:
                        # No conflict, add parameter
                        self._descriptors[name] = parent._descriptors[name]
                        self._defaults[name] = parent._defaults[name]
                        # Get the actual current value from parent
                        parent_value = parent.get(name)
                        self._values[name] = parent_value
                        self._inheritance_sources[name] = parent

        else:
            raise ValueError(f"Unknown inheritance strategy: {strategy}")

    def get_inheritance_info(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get inheritance information for a parameter.

        Args:
            name: Parameter name

        Returns:
            Dictionary with inheritance information, or None if not available
        """
        if name not in self._descriptors:
            return None

        descriptor = self._descriptors[name]

        # Check if parameter is inherited (not in _modified set and has different value than default)
        current_value = self.get(name)
        is_inherited = (
            name not in self._modified
            and current_value != descriptor.default
            and name in self._values
        )

        return {
            "name": name,
            "current_value": current_value,
            "default_value": descriptor.default,
            "is_modified": name in self._modified,
            "type": descriptor.type_,
            "has_validator": descriptor.validator is not None,
            "doc": descriptor.doc,
            "is_locked": name in self._locked_params,
            "group": self._param_to_group.get(name),
            "has_lazy_default": name in self._lazy_defaults,
            "dependents": self._dependencies.get(name, []),
            "depends_on": self._dependents.get(name, []),
            "inherited": is_inherited,
            "source": self._inheritance_sources.get(name),
        }

    # Parameter locking methods
    def lock_parameter(self, name: str) -> None:
        """Lock a parameter to prevent modification."""
        if name in self._descriptors:
            self._locked_params.add(name)
        else:
            raise ValueError(f"Parameter '{name}' does not exist")

    def unlock_parameter(self, name: str) -> None:
        """Unlock a parameter to allow modification."""
        self._locked_params.discard(name)

    def is_locked(self, name: str) -> bool:
        """Check if a parameter is locked."""
        return name in self._locked_params

    def get_locked_parameters(self) -> List[str]:
        """Get list of locked parameter names."""
        return list(self._locked_params)

    # Parameter grouping methods
    def create_group(self, group_name: str, param_names: List[str]) -> None:
        """
        Create a parameter group.

        Args:
            group_name: Name of the group
            param_names: List of parameter names to include in the group
        """
        # Validate that all parameters exist
        invalid_params = [name for name in param_names if name not in self._descriptors]
        if invalid_params:
            raise AttributeError(f"Invalid parameters for group '{group_name}': {invalid_params}")

        self._param_groups[group_name] = param_names.copy()

        # Update reverse mapping
        for param_name in param_names:
            self._param_to_group[param_name] = group_name

    def get_group(self, group_name: str) -> List[str]:
        """Get parameter names in a group."""
        return self._param_groups.get(group_name, []).copy()

    def get_parameter_group(self, param_name: str) -> Optional[str]:
        """Get the group name for a parameter."""
        return self._param_to_group.get(param_name)

    def set_group(self, group_name: str, values: Dict[str, Any]) -> None:
        """Set values for all parameters in a group."""
        if group_name not in self._param_groups:
            raise ValueError(f"Group '{group_name}' does not exist")

        group_params = self._param_groups[group_name]
        filtered_values = {k: v for k, v in values.items() if k in group_params}
        self.update(filtered_values)

    def get_group_values(self, group_name: str) -> Dict[str, Any]:
        """Get values for all parameters in a group."""
        if group_name not in self._param_groups:
            raise ValueError(f"Group '{group_name}' does not exist")

        group_params = self._param_groups[group_name]
        return {name: self.get(name) for name in group_params}

    # Lazy defaults
    def set_lazy_default(self, name: str, lazy_func: Callable[[], Any]) -> None:
        """
        Set a lazy default function for a parameter.

        Args:
            name: Parameter name
            lazy_func: Function that returns the default value when called
        """
        if name not in self._descriptors:
            raise ValueError(f"Parameter '{name}' does not exist")

        self._lazy_defaults[name] = lazy_func
        self._invalidate_cache(name)

    def clear_lazy_default(self, name: str) -> None:
        """Clear lazy default for a parameter."""
        if name in self._lazy_defaults:
            del self._lazy_defaults[name]
            self._invalidate_cache(name)

    # Change callbacks
    def add_change_callback(
        self, callback: Callable[[str, Any, Any], None], param_name: Optional[str] = None
    ) -> None:
        """
        Add a callback function that will be called when parameters change.

        Args:
            callback: Function to call with (param_name, old_value, new_value)
            param_name: Specific parameter to watch, or None for all parameters
        """
        if not self._enable_callbacks:
            return

        if param_name is None:
            # Global callback
            if self._global_callbacks is not None:
                self._global_callbacks.append(callback)
        else:
            # Parameter-specific callback
            if self._change_callbacks is not None:
                if param_name not in self._change_callbacks:
                    self._change_callbacks[param_name] = []
                self._change_callbacks[param_name].append(callback)

    def remove_change_callback(
        self, callback: Callable[[str, Any, Any], None], param_name: Optional[str] = None
    ) -> None:
        """Remove a change callback."""
        if not self._enable_callbacks:
            return

        if param_name is None:
            # Remove from global callbacks
            if self._global_callbacks is not None and callback in self._global_callbacks:
                self._global_callbacks.remove(callback)
        else:
            # Remove from parameter-specific callbacks
            if (
                self._change_callbacks is not None
                and param_name in self._change_callbacks
                and callback in self._change_callbacks[param_name]
            ):
                self._change_callbacks[param_name].remove(callback)

    def _trigger_change_callbacks(self, name: str, old_value: Any, new_value: Any) -> None:
        """Trigger change callbacks for a parameter."""
        if not self._enable_callbacks:
            return

        # Trigger parameter-specific callbacks
        if self._change_callbacks is not None and name in self._change_callbacks:
            for callback in self._change_callbacks[name]:
                try:
                    callback(name, old_value, new_value)
                except Exception:
                    # Log error but don't fail the parameter change
                    # print(f"Warning: Change callback failed for parameter '{name}': {e}")  # Removed for performance
                    pass

        # Trigger global callbacks
        if self._global_callbacks is not None:
            for callback in self._global_callbacks:
                try:
                    callback(name, old_value, new_value)
                except Exception:
                    # print(f"Warning: Global change callback failed for parameter '{name}': {e}")  # Removed for performance
                    pass

    # History methods
    def get_change_history(self, name: str, limit: Optional[int] = None) -> List[tuple]:
        """
        Get change history for a parameter.

        Args:
            name: Parameter name
            limit: Maximum number of history entries to return

        Returns:
            List of history entries (newest first) in format (old_value, new_value, timestamp)
        """
        if not self._enable_history or self._change_history is None:
            return []

        history = self._change_history.get(name, [])

        # Sort by timestamp (newest first)
        sorted_history = sorted(history, key=lambda x: x["timestamp"], reverse=True)

        if limit is not None:
            sorted_history = sorted_history[:limit]

        # Convert to tuple format (old_value, new_value, timestamp)
        return [
            (entry["old_value"], entry["new_value"], entry["timestamp"]) for entry in sorted_history
        ]

    def clear_history(self, name: Optional[str] = None) -> None:
        """
        Clear change history.

        Args:
            name: Specific parameter name, or None to clear all history
        """
        if not self._enable_history or self._change_history is None:
            return

        if name is None:
            self._change_history.clear()
        elif name in self._change_history:
            del self._change_history[name]

    # Dependency management
    def add_dependency(self, param_name: str, dependent_param: str) -> None:
        """
        Add a dependency relationship between parameters.

        Args:
            param_name: Parameter that others depend on
            dependent_param: Parameter that depends on param_name
        """
        # Validate parameters exist
        if param_name not in self._descriptors:
            raise AttributeError(f"Parameter '{param_name}' does not exist")
        if dependent_param not in self._descriptors:
            raise AttributeError(f"Dependent parameter '{dependent_param}' does not exist")

        # Add to dependencies
        if param_name not in self._dependencies:
            self._dependencies[param_name] = []
        if dependent_param not in self._dependencies[param_name]:
            self._dependencies[param_name].append(dependent_param)

        # Add to dependents (reverse mapping)
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
        """Get list of parameters that this parameter depends on."""
        return self._dependents.get(param_name, []).copy()

    def _update_dependents(self, param_name: str, new_value: Any) -> None:
        """Update dependent parameters when a parameter changes."""
        if param_name in self._dependencies:
            for dependent in self._dependencies[param_name]:
                # This is a placeholder for custom dependency logic
                # In a real implementation, you might have specific update rules
                pass

    # Transaction support
    def begin_transaction(self) -> None:
        """Begin a parameter transaction."""
        if self._in_transaction:
            raise RuntimeError("Already in a transaction")

        self._in_transaction = True
        self._transaction_snapshot = {
            "values": self._values.copy(),
            "modified": self._modified.copy(),
        }

    def commit_transaction(self) -> None:
        """Commit the current transaction."""
        if not self._in_transaction:
            raise RuntimeError("Not in a transaction")

        # Collect changes made during transaction for callbacks
        if self._enable_callbacks and self._transaction_snapshot:
            old_values = self._transaction_snapshot["values"]
            for name in self._values:
                if name not in old_values or self._values[name] != old_values.get(name):
                    # Parameter was changed during transaction
                    old_value = old_values.get(name, self._defaults.get(name))
                    new_value = self._values[name]
                    self._trigger_change_callbacks(name, old_value, new_value)

        # Transaction is committed by keeping current state
        self._in_transaction = False
        self._transaction_snapshot = None

    def rollback_transaction(self) -> None:
        """Rollback the current transaction."""
        if not self._in_transaction:
            raise RuntimeError("Not in a transaction")

        # Restore snapshot
        if self._transaction_snapshot:
            self._values = self._transaction_snapshot["values"].copy()
            self._modified = self._transaction_snapshot["modified"].copy()

        self._in_transaction = False
        self._transaction_snapshot = None

        # Clear cache since values changed
        self._clear_cache()

    def is_in_transaction(self) -> bool:
        """Check if currently in a transaction."""
        return self._in_transaction


class ParameterAccessor:
    """
    Parameter accessor that provides dict-like and attribute-like access to parameters.

    This class serves as a bridge between the new parameter system and the old
    MetaParams-style parameter access patterns. It provides backward compatibility
    by supporting both attribute access (obj.p.param_name) and dict-like access.
    """

    def __init__(self, param_manager: ParameterManager):
        """
        Initialize with a parameter manager.

        NOTE: 原本尝试预创建实例属性以优化性能，但会导致参数同步问题。
        当通过其他方式（如broker.set_cash()）修改参数时，实例属性不会更新。
        因此保持动态查找，确保总是获取最新值。
        """
        # Use object.__setattr__ to avoid our custom __setattr__
        object.__setattr__(self, "_param_manager", param_manager)

        # Create a dict-like interface for _getitems() compatibility
        object.__setattr__(self, "_items_cache", None)

    def __getattr__(self, name):
        """
        Get parameter value via attribute access.

        总是从param_manager获取最新值，确保一致性。
        所有参数访问都动态查找，保证获取最新值。
        """
        # Use object.__getattribute__ to avoid recursion during unpickling
        param_manager = object.__getattribute__(self, "_param_manager")
        return param_manager.get(name)

    def __setattr__(self, name, value):
        """Set parameter value via attribute access."""
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self._param_manager.set(name, value)

    def __getitem__(self, name):
        """Get parameter value via dict-like access."""
        return self._param_manager.get(name)

    def __setitem__(self, name, value):
        """Set parameter value via dict-like access."""
        self._param_manager.set(name, value)

    def __contains__(self, name):
        """Check if parameter exists."""
        return name in self._param_manager

    def __iter__(self):
        """Iterate over parameter names."""
        return iter(self._param_manager)

    def __len__(self):
        """Get number of parameters."""
        return len(self._param_manager)

    def _getitems(self):
        """Get parameter items as list of tuples (name, value) for MetaParams compatibility."""
        return list(self._param_manager.items())

    def _getkeys(self):
        """Get parameter keys for MetaParams compatibility."""
        return list(self._param_manager.keys())

    def _getvalues(self):
        """Get parameter values for MetaParams compatibility."""
        return list(self._param_manager.values())

    def _getkwargs(self, skip_=False):
        """
        Get parameters as keyword arguments for MetaParams compatibility.

        Args:
            skip_: Whether to skip parameters starting with underscore

        Returns:
            Dictionary of parameter names and values
        """
        kwargs = {}
        for name, value in self._param_manager.items():
            if skip_ and name.startswith("_"):
                continue
            kwargs[name] = value
        return kwargs

    def __repr__(self):
        """String representation showing parameter values."""
        items = list(self._param_manager.items())
        return f"ParameterAccessor({dict(items)})"


class ParameterizedBase:
    """
    Enhanced base class for objects with parameters - without metaclass.

    This class provides the modern parameter system interface while maintaining
    backward compatibility with the old MetaParams-based system. It uses
    regular class mechanisms instead of metaclass.
    """

    def __init_subclass__(cls, **kwargs):
        """
        Called when a class is subclassed. Replaces metaclass functionality.

        This method sets up the class for lazy parameter descriptor resolution
        to avoid inheritance contamination issues.
        """
        super().__init_subclass__(**kwargs)

        # Don't compute _parameter_descriptors here - do it lazily
        # This prevents child class definitions from affecting parent classes
        cls._parameter_descriptors = None  # Mark as not computed
        cls._parameter_descriptors_computed = False

        # Check for MetaParams compatibility
        cls._has_metaparams_heritage = any(
            hasattr(base, "params") and hasattr(getattr(base, "params", None), "_getitems")
            for base in cls.__mro__[1:]  # Skip self
        )

    @classmethod
    def _compute_parameter_descriptors(cls):
        """
        Compute parameter descriptors for this class on-demand.

        This is called lazily to avoid inheritance contamination issues
        that occur when descriptors are computed during class definition.
        """
        if cls._parameter_descriptors_computed:
            return cls._parameter_descriptors

        # Create a completely new _parameter_descriptors for this class
        # Each class must have its own independent dictionary

        # STEP 1: Collect all parameters from the inheritance hierarchy
        # Process base classes in reverse MRO order to respect inheritance precedence
        all_params = {}

        # Process base classes from least specific to most specific
        # This way, more specific classes override less specific ones
        for base_cls in reversed(cls.__mro__[1:-1]):  # Skip cls and object, reverse order
            # FIRST: Look for parameter descriptors directly defined in this base class
            if hasattr(base_cls, "__dict__"):
                for attr_name, attr_value in base_cls.__dict__.items():
                    if isinstance(attr_value, ParameterDescriptor):
                        # More specific classes override less specific ones
                        # Since we process from least to most specific, always update
                        all_params[attr_name] = attr_value

            # SECOND: Look for legacy params tuple in this base class
            if hasattr(base_cls, "__dict__") and "params" in base_cls.__dict__:
                base_params = base_cls.__dict__["params"]
                if isinstance(base_params, (tuple, list)):
                    for param_def in base_params:
                        if isinstance(param_def, (tuple, list)) and len(param_def) >= 2:
                            param_name, param_default = param_def[0], param_def[1]
                            # More specific classes override less specific ones
                            # Since we process from least to most specific, always update
                            all_params[param_name] = ParameterDescriptor(
                                default=param_default, name=param_name
                            )

        # STEP 2: Add descriptors from the current class (highest precedence)
        # These override any inherited parameters with the same name
        if hasattr(cls, "__dict__"):
            for attr_name, attr_value in cls.__dict__.items():
                if isinstance(attr_value, ParameterDescriptor):
                    all_params[attr_name] = attr_value
                    # Ensure descriptor has proper name set
                    if attr_value.name is None:
                        attr_value.name = attr_name
                        attr_value._attr_name = f"_param_{attr_name}"

        # STEP 3: Handle legacy params definition in current class
        if hasattr(cls, "__dict__") and "params" in cls.__dict__:
            current_params = cls.__dict__["params"]
            if isinstance(current_params, (tuple, list)):
                for param_def in current_params:
                    if isinstance(param_def, (tuple, list)) and len(param_def) >= 2:
                        param_name, param_default = param_def[0], param_def[1]
                        # Current class params override inherited ones
                        all_params[param_name] = ParameterDescriptor(
                            default=param_default, name=param_name
                        )

        # STEP 4: Set the final descriptors for this class and mark as computed
        cls._parameter_descriptors = all_params
        cls._parameter_descriptors_computed = True

        return all_params

    def __init__(self, **kwargs):
        """Initialize the parameterized object."""
        # Initialize parent first
        super().__init__()

        # Get parameter descriptors from the class hierarchy
        descriptors = self._compute_parameter_descriptors()

        if descriptors:
            # Use the modern parameter system
            self._init_with_new_system(descriptors, kwargs)
        else:
            # Fall back to compatibility mode if needed
            legacy_params = getattr(self, "params", ())
            if legacy_params:
                # Convert legacy params to descriptors
                legacy_descriptors = ParamsBridge.convert_legacy_params_tuple(legacy_params)
                self._init_with_metaparams_compatibility(legacy_descriptors, kwargs)
            else:
                # No parameters at all
                self._param_manager = ParameterManager({})

        # Set up parameter accessor as 'p' for backward compatibility
        if hasattr(self, "_param_manager"):
            self.p = ParameterAccessor(self._param_manager)
            # Also create 'params' accessor for full compatibility
            self.params = self.p
        else:
            self.p = None
            self.params = None

    def _get_parameter_descriptors(self) -> Dict[str, ParameterDescriptor]:
        """
        Get parameter descriptors from the class hierarchy.

        Returns:
            Dictionary of parameter descriptors
        """
        return self.__class__._compute_parameter_descriptors()

    def _init_with_metaparams_compatibility(
        self, descriptors: Dict[str, ParameterDescriptor], kwargs: Dict[str, Any]
    ):
        """
        Initialize with MetaParams compatibility mode.

        Args:
            descriptors: Parameter descriptors
            kwargs: Initialization keyword arguments
        """
        # Initialize the new parameter manager
        self._param_manager = ParameterManager(
            descriptors, enable_history=True, enable_callbacks=True
        )

        # Handle inheritance from MetaParams-based classes
        if self._has_metaparams_heritage:
            for base in self.__class__.__mro__[1:]:  # Skip self
                if hasattr(base, "params") and hasattr(getattr(base, "params", None), "_getitems"):
                    # Extract parameters from MetaParams base
                    try:
                        for param_name, param_default in base.params._getitems():
                            if param_name not in descriptors:
                                # Create a descriptor for the MetaParams parameter
                                descriptors[param_name] = ParameterDescriptor(
                                    default=param_default, name=param_name
                                )
                                self._param_manager._descriptors[param_name] = descriptors[
                                    param_name
                                ]
                                self._param_manager._defaults[param_name] = param_default
                                self._inheritance_sources[param_name] = base
                    except (AttributeError, TypeError):
                        # Skip if _getitems() doesn't work as expected
                        pass

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
                self._handle_initialization_error(e)

        # Return other kwargs for parent class initialization
        return other_kwargs

    def _init_with_new_system(
        self, descriptors: Dict[str, ParameterDescriptor], kwargs: Dict[str, Any]
    ):
        """
        Initialize with the new parameter system only.

        Args:
            descriptors: Parameter descriptors
            kwargs: Initialization keyword arguments
        """
        self._param_manager = ParameterManager(
            descriptors, enable_history=True, enable_callbacks=True
        )

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
            try:
                self._param_manager.update(param_kwargs)
            except Exception as e:
                self._handle_initialization_error(e)

        # Return other kwargs for parent class initialization
        return other_kwargs

    def _handle_initialization_error(self, error: Exception):
        """
        Handle initialization errors with enhanced error messages.

        Args:
            error: The original exception
        """
        error_msg = f"Parameter initialization failed for {self.__class__.__name__}: {error}"

        # Add helpful information about available parameters
        if hasattr(self, "_param_manager"):
            available_params = list(self._param_manager.keys())
            if available_params:
                error_msg += f". Available parameters: {available_params}"

        # Re-raise with enhanced message
        if isinstance(error, (ValueError, TypeError)):
            raise type(error)(error_msg) from error
        else:
            raise ValueError(error_msg) from error

    # Parameter access methods for backward compatibility and convenience
    def get_param(self, name: str, default: Any = None) -> Any:
        """
        Get parameter value with fallback.

        Args:
            name: Parameter name
            default: Default value if parameter not found

        Returns:
            Parameter value
        """
        try:
            return object.__getattribute__(self, "_param_manager").get(name, default)
        except AttributeError:
            return default

    def set_param(self, name: str, value: Any, validate: bool = True) -> None:
        """
        Set parameter value with optional validation.

        Args:
            name: Parameter name
            value: Parameter value
            validate: Whether to perform validation

        Raises:
            AttributeError: If parameter manager not initialized
            ValueError: If validation fails
        """
        try:
            param_manager = object.__getattribute__(self, "_param_manager")
        except AttributeError:
            raise AttributeError(f"Parameter manager not initialized for {self.__class__.__name__}")

        try:
            param_manager.set(name, value, skip_validation=not validate)
        except Exception as e:
            raise ValueError(f"Failed to set parameter '{name}' to {value}: {e}") from e

    def get_param_info(self) -> Dict[str, Dict[str, Any]]:
        """
        Get comprehensive information about all parameters.

        Returns:
            Dictionary with parameter information
        """
        try:
            param_manager = object.__getattribute__(self, "_param_manager")
        except AttributeError:
            return {}

        info = {}
        for name in param_manager.keys():
            inheritance_info = param_manager.get_inheritance_info(name)
            if inheritance_info:
                info[name] = inheritance_info
            else:
                # Fallback for parameters without inheritance info
                info[name] = {
                    "name": name,
                    "current_value": param_manager.get(name),
                    "type": "unknown",
                }

        return info

    def validate_params(self) -> List[str]:
        """
        Validate all parameters and return list of validation errors.

        Returns:
            List of validation error messages (empty if all valid)
        """
        if not hasattr(self, "_param_manager"):
            return []

        errors = []
        for name, descriptor in self._param_manager._descriptors.items():
            current_value = self._param_manager.get(name)
            if not descriptor.validate(current_value):
                errors.append(f"Parameter '{name}' has invalid value: {current_value}")

        return errors

    def reset_param(self, name: str) -> None:
        """
        Reset parameter to its default value.

        Args:
            name: Parameter name

        Raises:
            AttributeError: If parameter manager not initialized
            ValueError: If parameter doesn't exist or is locked
        """
        if not hasattr(self, "_param_manager"):
            raise AttributeError(f"Parameter manager not initialized for {self.__class__.__name__}")

        try:
            self._param_manager.reset(name)
        except Exception as e:
            raise ValueError(f"Failed to reset parameter '{name}': {e}") from e

    def reset_all_params(self) -> None:
        """Reset all parameters to their default values."""
        if hasattr(self, "_param_manager"):
            for name in list(self._param_manager.keys()):
                try:
                    self._param_manager.reset(name)
                except Exception:
                    # Continue with other parameters even if one fails
                    pass

    def get_modified_params(self) -> Dict[str, Any]:
        """
        Get parameters that have been modified from their defaults.

        Returns:
            Dictionary of modified parameter names and values
        """
        if not hasattr(self, "_param_manager"):
            return {}

        modified = {}
        for name in self._param_manager._modified:
            modified[name] = self._param_manager.get(name)

        return modified

    def copy_params_from(
        self,
        other: "ParameterizedBase",
        param_names: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        """
        Copy parameters from another ParameterizedBase instance.

        Args:
            other: Source object to copy parameters from
            param_names: Specific parameter names to copy (None for all)
            exclude: Parameter names to exclude from copying
        """
        if not hasattr(self, "_param_manager") or not hasattr(other, "_param_manager"):
            return

        # Determine which parameters to copy
        if param_names is None:
            param_names = list(other._param_manager.keys())

        if exclude:
            param_names = [name for name in param_names if name not in exclude]

        # Copy parameters
        for name in param_names:
            if (
                name in self._param_manager._descriptors
                and name in other._param_manager._descriptors
            ):
                try:
                    value = other._param_manager.get(name)
                    self._param_manager.set(name, value)
                except Exception:
                    # Skip parameters that can't be copied
                    pass

    def __repr__(self) -> str:
        """Enhanced string representation with parameter information."""
        class_name = self.__class__.__name__
        if hasattr(self, "_param_manager") and self._param_manager:
            param_count = len(self._param_manager)
            return f"{class_name}(parameters={param_count})"
        else:
            return f"{class_name}(no_parameters)"


# CRITICAL FIX: Picklable validator classes for multiprocessing support
# Local functions returned by Int() and Float() cannot be pickled,
# causing failures in strategy optimization (optstrategy).


class _IntValidator:
    """
    Integer validator that can be pickled for multiprocessing.

    CRITICAL FIX: Class-based validator instead of closure to support pickling.
    """

    def __init__(self, min_val=None, max_val=None):
        self.min_val = min_val
        self.max_val = max_val

    def __call__(self, value):
        # Only accept actual int values, not floats or other types
        if not isinstance(value, int) or isinstance(value, bool):
            return False
        try:
            int_val = int(value)
            if self.min_val is not None and int_val < self.min_val:
                return False
            if self.max_val is not None and int_val > self.max_val:
                return False
            return True
        except (ValueError, TypeError):
            return False

    def __reduce__(self):
        """Support pickling for multiprocessing."""
        return (_IntValidator, (self.min_val, self.max_val))


class _FloatValidator:
    """
    Float validator that can be pickled for multiprocessing.

    CRITICAL FIX: Class-based validator instead of closure to support pickling.
    """

    def __init__(self, min_val=None, max_val=None):
        self.min_val = min_val
        self.max_val = max_val

    def __call__(self, value):
        # Only accept actual numeric types, not strings
        if not isinstance(value, (int, float)):
            return False
        try:
            float_val = float(value)
            if self.min_val is not None and float_val < self.min_val:
                return False
            if self.max_val is not None and float_val > self.max_val:
                return False
            return True
        except (ValueError, TypeError):
            return False

    def __reduce__(self):
        """Support pickling for multiprocessing."""
        return (_FloatValidator, (self.min_val, self.max_val))


class _BoolValidator:
    """
    Boolean validator that can be pickled for multiprocessing.

    CRITICAL FIX: Class-based validator instead of closure to support pickling.
    """

    def __call__(self, value):
        """Boolean validator that accepts various boolean representations."""
        if isinstance(value, bool):
            return True
        if value in (0, 1, "True", "False", "true", "false", "TRUE", "FALSE"):
            return True
        return False

    def __reduce__(self):
        """Support pickling for multiprocessing."""
        return (_BoolValidator, ())


class _StringValidator:
    """
    String validator that can be pickled for multiprocessing.

    CRITICAL FIX: Class-based validator instead of closure to support pickling.
    """

    def __init__(self, min_length=None, max_length=None):
        self.min_length = min_length
        self.max_length = max_length

    def __call__(self, value):
        if not isinstance(value, string_types):
            return False
        if self.min_length is not None and len(value) < self.min_length:
            return False
        if self.max_length is not None and len(value) > self.max_length:
            return False
        return True

    def __reduce__(self):
        """Support pickling for multiprocessing."""
        return (_StringValidator, (self.min_length, self.max_length))


class _OneOfValidator:
    """
    OneOf validator that can be pickled for multiprocessing.

    CRITICAL FIX: Class-based validator instead of closure to support pickling.
    """

    def __init__(self, choices):
        self.choices = choices

    def __call__(self, value):
        return value in self.choices

    def __reduce__(self):
        """Support pickling for multiprocessing."""
        return (_OneOfValidator, (self.choices,))


# Convenience functions for creating parameter descriptors with validation
def Int(min_val: Optional[int] = None, max_val: Optional[int] = None) -> Callable[[Any], bool]:
    """
    Create an integer validator function.

    Args:
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        Validator function for integer parameters
    """
    return _IntValidator(min_val, max_val)


def Float(
    min_val: Optional[float] = None, max_val: Optional[float] = None
) -> Callable[[Any], bool]:
    """
    Create a float validator function.

    Args:
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        Validator function for float parameters
    """
    return _FloatValidator(min_val, max_val)


# Convenience functions for creating typed parameter descriptors
def FloatParam(
    default=None, min_val: Optional[float] = None, max_val: Optional[float] = None, doc: str = None
) -> ParameterDescriptor:
    """Create a float parameter descriptor with validation."""
    return ParameterDescriptor(
        default=default, type_=float, validator=Float(min_val, max_val), doc=doc
    )


def BoolParam(default=None, doc: str = None) -> ParameterDescriptor:
    """Create a boolean parameter descriptor."""
    return ParameterDescriptor(default=default, type_=bool, validator=_BoolValidator(), doc=doc)


def StringParam(
    default=None,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    doc: str = None,
) -> ParameterDescriptor:
    """Create a string parameter descriptor with length validation."""
    return ParameterDescriptor(
        default=default, type_=str, validator=String(min_length, max_length), doc=doc
    )


def String(
    min_length: Optional[int] = None, max_length: Optional[int] = None
) -> Callable[[Any], bool]:
    """
    Create a string validator function.

    Args:
        min_length: Minimum allowed string length
        max_length: Maximum allowed string length

    Returns:
        Validator function for string parameters
    """
    return _StringValidator(min_length, max_length)


def Bool() -> Callable[[Any], bool]:
    """
    Create a boolean validator function.

    Returns:
        Validator function for boolean parameters
    """
    return _BoolValidator()


def OneOf(*choices) -> Callable[[Any], bool]:
    """
    Create a validator that checks if value is one of the given choices.

    Args:
        *choices: Allowed values

    Returns:
        Validator function
    """
    return _OneOfValidator(choices)


def create_param_descriptor(name: str, default: Any = None, doc: str = None) -> ParameterDescriptor:
    """
    Create a basic parameter descriptor.

    Args:
        name: Parameter name
        default: Default value
        doc: Documentation string

    Returns:
        ParameterDescriptor instance
    """
    return ParameterDescriptor(default=default, name=name, doc=doc)


def derive_params(base_params, new_params, other_base_params=None):
    """
    Derive parameters by combining base parameters with new ones.

    Args:
        base_params: Base parameter descriptors or tuples
        new_params: New parameter descriptors or tuples
        other_base_params: Additional base parameters

    Returns:
        Dictionary of combined parameter descriptors
    """
    combined_params = {}

    # Add base parameters
    if hasattr(base_params, "_parameter_descriptors"):
        combined_params.update(base_params._parameter_descriptors)
    elif hasattr(base_params, "__mro__"):
        # It's a class, collect from all bases
        for base in base_params.__mro__:
            if hasattr(base, "_parameter_descriptors"):
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


class ParamsBridge:
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

        if hasattr(cls, "params") and hasattr(cls.params, "_getitems"):
            for param_name, param_default in cls.params._getitems():
                descriptors[param_name] = ParameterDescriptor(
                    default=param_default,
                    name=param_name,
                    doc=f"Migrated from MetaParams class {cls.__name__}",
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
                        doc="Converted from legacy params tuple",
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
        descriptors = ParamsBridge.extract_params_from_metaparams_class(metaparams_class)

        # Create new class with descriptor-based parameters
        class_name = f"Modern{metaparams_class.__name__}"

        # Build class namespace
        namespace = {
            "__module__": metaparams_class.__module__,
            "__doc__": f"Modernized version of {metaparams_class.__name__} with descriptor-based parameters",
        }

        # Add parameter descriptors to namespace
        for name, descriptor in descriptors.items():
            namespace[name] = descriptor

        # Create the new class using regular class creation (no metaclass)
        new_class = type(class_name, (ParameterizedBase,), namespace)

        return new_class


class ParameterValidationError(ValueError):
    """Specific exception for parameter validation errors."""

    def __init__(
        self,
        parameter_name: str,
        value: Any,
        expected_type: Optional[Type] = None,
        additional_info: str = "",
    ):
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
        "compatible": True,
        "missing_params": [],
        "extra_params": [],
        "type_mismatches": [],
        "default_mismatches": [],
    }

    # Get old parameters
    old_params = {}
    if hasattr(old_class, "params") and hasattr(old_class.params, "_getitems"):
        old_params = dict(old_class.params._getitems())

    # Get new parameters
    new_params = {}
    if hasattr(new_class, "_parameter_descriptors"):
        new_params = {name: desc.default for name, desc in new_class._parameter_descriptors.items()}

    # Check for missing parameters
    for name in old_params:
        if name not in new_params:
            results["missing_params"].append(name)
            results["compatible"] = False

    # Check for extra parameters
    for name in new_params:
        if name not in old_params:
            results["extra_params"].append(name)

    # Check for default value mismatches
    for name in old_params:
        if name in new_params:
            if old_params[name] != new_params[name]:
                results["default_mismatches"].append(
                    {
                        "param": name,
                        "old_default": old_params[name],
                        "new_default": new_params[name],
                    }
                )

    return results
