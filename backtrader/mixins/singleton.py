#!/usr/bin/env python
"""Singleton Mixin Module - Singleton pattern implementation.

This module provides the SingletonMixin class for implementing the
singleton pattern without using metaclasses. This is part of the
metaprogramming removal effort in backtrader.

Classes:
    SingletonMixin: Mixin class that implements the singleton pattern.
    ParameterizedSingletonMixin: Singleton mixin with parameter support.
    StoreBase: Base class for store singletons.

Example:
    Creating a singleton class:
    >>> class MyClass(SingletonMixin):
    ...     pass
    >>> a = MyClass()
    >>> b = MyClass()
    >>> assert a is b  # True - same instance
"""

import threading
import weakref
from typing import Any, Dict, Optional


class SingletonMixin:
    """Mixin class to implement singleton pattern using __new__ method.

    This replaces the MetaSingleton metaclass pattern, providing the same
    functionality without using metaclasses. Each class that inherits from
    this mixin will maintain exactly one instance per class.

    Thread-safe implementation using threading.Lock.

    Features:
    - Thread-safe singleton creation
    - Per-class singleton instances (subclasses get their own instances)
    - Automatic cleanup when instances are garbage collected
    - Maintains compatibility with existing parameter systems
    """

    # Class-level storage for singleton instances
    # Using WeakValueDictionary for automatic cleanup
    _instances: Dict[type, Any] = weakref.WeakValueDictionary()
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """Create or return existing singleton instance for the class."""

        # Check if instance already exists (fast path, no lock)
        if cls in cls._instances:
            return cls._instances[cls]

        # Acquire lock for thread-safe creation
        with cls._lock:
            # Double-check pattern: instance might have been created
            # by another thread while waiting for lock
            if cls in cls._instances:
                return cls._instances[cls]

            # Create new instance using parent's __new__
            # Skip SingletonMixin in MRO to avoid recursion
            for base in cls.__mro__[1:]:
                if base is not SingletonMixin and hasattr(base, "__new__"):
                    instance = base.__new__(cls)
                    break
            else:
                # Fallback to object.__new__ if no suitable base found
                instance = object.__new__(cls)

            # Store instance before calling __init__ to handle potential
            # recursive calls during initialization
            cls._instances[cls] = instance

            return instance

    @classmethod
    def _reset_instance(cls):
        """Reset the singleton instance for this class.

        This is mainly for testing purposes and should be used with caution
        in production code.
        """
        with cls._lock:
            if cls in cls._instances:
                del cls._instances[cls]

    @classmethod
    def _get_instance(cls) -> Optional[Any]:
        """Get the current singleton instance if it exists.

        Returns:
            The singleton instance if it exists, None otherwise.
        """
        return cls._instances.get(cls)

    @classmethod
    def _has_instance(cls) -> bool:
        """Check if a singleton instance exists for this class.

        Returns:
            True if instance exists, False otherwise.
        """
        return cls in cls._instances


class ParameterizedSingletonMixin(SingletonMixin):
    """Enhanced singleton mixin that integrates with parameter systems.

    This version is specifically designed to work with backtrader's
    parameter system, maintaining compatibility with MetaParams functionality.
    """

    def __new__(cls, *args, **kwargs):
        """Create singleton instance with parameter support."""
        instance = super().__new__(cls)

        # Only initialize once
        if not hasattr(instance, "_singleton_initialized"):
            instance._singleton_initialized = False

        return instance

    def __init__(self, *args, **kwargs):
        """Initialize singleton instance only once."""
        if self._singleton_initialized:
            return

        # Call parent __init__ methods
        super().__init__(*args, **kwargs)
        self._singleton_initialized = True


# Backward compatibility alias
StoreBase = ParameterizedSingletonMixin
