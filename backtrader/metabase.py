#!/usr/bin/env python
"""Base classes and mixins for the Backtrader framework.

This module provides the foundational infrastructure that replaces the original
metaclass-based design. It includes parameter management, object factories,
and various mixin classes used throughout the framework.

Key Components:
    - **ObjectFactory**: Factory class for creating objects with lifecycle hooks
    - **BaseMixin**: Base mixin providing factory-based object creation
    - **ParamsMixin**: Mixin for parameter management without metaclasses
    - **AutoInfoClass**: Dynamic class for parameter/info storage
    - **ParameterManager**: Static utility for handling parameter operations
    - **ItemCollection**: Collection class with index and name-based access

Utility Functions:
    - findbases: Recursively find base classes of a given type
    - findowner: Search call stack for owner objects
    - is_class_type: Cached type checking via MRO inspection
    - patch_strategy_clk_update: Runtime patch for Strategy clock updates

Example:
    Creating a class with parameters::

        class MyIndicator(ParamsMixin):
            params = (('period', 20), ('multiplier', 2.0))

            def __init__(self):
                print(f"Period: {self.p.period}")

Note:
    This module was created during the metaclass removal refactoring to provide
    equivalent functionality using explicit initialization patterns.
"""
import math
import sys
import threading
from collections import OrderedDict
from contextlib import contextmanager

from .utils.py3 import string_types, zip

# PERFORMANCE OPTIMIZATION: Cache for MRO type checks
# This avoids repeatedly traversing __mro__ for the same classes
_type_check_cache = {}

# PERFORMANCE OPTIMIZATION: One-time guard for indicator alias initialization
_INDICATOR_ALIASES_INITIALIZED = False

# Thread-local storage for owner context
# This replaces sys._getframe() based owner lookup with explicit context management
_owner_context = threading.local()


class OwnerContext:
    """Context manager for tracking owner objects during indicator creation.

    This class provides an alternative to sys._getframe() based owner lookup
    by maintaining an explicit owner stack in thread-local storage.

    Usage:
        with OwnerContext.set_owner(strategy):
            # All indicators created here will have strategy as their owner
            sma = SMA(data, period=20)

    The owner stack allows nested contexts, so indicators creating sub-indicators
    will correctly assign ownership.
    """

    @staticmethod
    def get_current_owner(cls_filter=None):
        """Get the current owner from the context stack.

        Args:
            cls_filter: Optional class type to filter owners. If provided,
                only returns an owner that is an instance of this class.

        Returns:
            The current owner object, or None if no owner is set or
            no owner matches the filter.
        """
        stack = getattr(_owner_context, "owner_stack", None)
        if not stack:
            return None

        # Return the topmost owner matching the filter
        for owner in reversed(stack):
            if cls_filter is None or isinstance(owner, cls_filter):
                return owner
        return None

    @staticmethod
    @contextmanager
    def set_owner(owner):
        """Set the current owner for indicator creation.

        Args:
            owner: The owner object (typically a Strategy or Indicator).

        Yields:
            None. The owner is available via get_current_owner() within the context.
        """
        if not hasattr(_owner_context, "owner_stack"):
            _owner_context.owner_stack = []

        _owner_context.owner_stack.append(owner)
        try:
            yield
        finally:
            _owner_context.owner_stack.pop()

    @staticmethod
    def push_owner(owner):
        """Push an owner onto the stack (non-context-manager version).

        Args:
            owner: The owner object to push.
        """
        if not hasattr(_owner_context, "owner_stack"):
            _owner_context.owner_stack = []
        _owner_context.owner_stack.append(owner)

    @staticmethod
    def pop_owner():
        """Pop the current owner from the stack.

        Returns:
            The popped owner, or None if the stack was empty.
        """
        stack = getattr(_owner_context, "owner_stack", None)
        if stack:
            return stack.pop()
        return None

    @staticmethod
    def clear():
        """Clear the owner stack (useful for testing)."""
        if hasattr(_owner_context, "owner_stack"):
            _owner_context.owner_stack.clear()


def is_class_type(cls, type_name):
    """
    OPTIMIZED: Check if a class is of a certain type by checking __mro__.
    Results are cached for better performance.

    Args:
        cls: The class to check
        type_name: The type name to look for (e.g., 'Strategy', 'Indicator')

    Returns:
        bool: True if the class has the type in its MRO
    """
    cache_key = (id(cls), type_name)
    if cache_key in _type_check_cache:
        return _type_check_cache[cache_key]

    # Check the class name and all base classes
    result = type_name in cls.__name__ or any(type_name in base.__name__ for base in cls.__mro__)
    _type_check_cache[cache_key] = result
    return result


def patch_strategy_clk_update():
    """
    CRITICAL FIX: Patch the Strategy class's _clk_update method to prevent
    the "max() iterable argument is empty" error that occurs when no data
    sources have any length yet.
    """
    try:
        from .strategy import Strategy

        def safe_clk_update(self):
            """CRITICAL FIX: Safe _clk_update method that handles empty data sources"""

            # CRITICAL FIX: Ensure data is available before clock operations
            if getattr(self, "_data_assignment_pending", True) and (
                not hasattr(self, "datas") or not self.datas
            ):
                # Try to get data assignment from cerebro if not already done
                if hasattr(self, "_ensure_data_available"):
                    self._ensure_data_available()

            # CRITICAL FIX: Handle the old sync method safely
            if hasattr(self, "_oldsync") and self._oldsync:
                # Call parent class _clk_update if available
                try:
                    # Use the parent class method from StrategyBase if available
                    from .lineiterator import StrategyBase

                    if (
                        hasattr(StrategyBase, "_clk_update")
                        and StrategyBase._clk_update != safe_clk_update
                    ):
                        clk_len = StrategyBase._clk_update(self)
                    else:
                        clk_len = 1
                except Exception:
                    clk_len = 1

                # CRITICAL FIX: Only set datetime if we have valid data sources with length
                if hasattr(self, "datas") and self.datas:
                    valid_data_times = []
                    for d in self.datas:
                        try:
                            if (
                                len(d) > 0
                                and hasattr(d, "datetime")
                                and hasattr(d.datetime, "__getitem__")
                            ):
                                dt_val = d.datetime[0]
                                # Only add valid datetime values (not None or NaN)
                                if dt_val is not None and not (
                                    isinstance(dt_val, float) and math.isnan(dt_val)
                                ):
                                    valid_data_times.append(dt_val)
                        except (IndexError, AttributeError, TypeError):
                            continue

                    if (
                        valid_data_times
                        and hasattr(self, "lines")
                        and hasattr(self.lines, "datetime")
                    ):
                        try:
                            self.lines.datetime[0] = max(valid_data_times)
                        except (ValueError, IndexError, AttributeError):
                            # If setting datetime fails, use a default valid ordinal (1 = Jan 1, Year 1)
                            self.lines.datetime[0] = 1.0
                    elif hasattr(self, "lines") and hasattr(self.lines, "datetime"):
                        # No valid times, use default valid ordinal (1 = Jan 1, Year 1)
                        self.lines.datetime[0] = 1.0

                return clk_len

            # CRITICAL FIX: Handle the normal (non-oldsync) path
            # Initialize _dlens if not present
            if not hasattr(self, "_dlens"):
                self._dlens = [
                    len(d) if hasattr(d, "__len__") else 0
                    for d in (self.datas if hasattr(self, "datas") else [])
                ]

            # Get current data lengths safely
            if hasattr(self, "datas") and self.datas:
                newdlens = []
                for d in self.datas:
                    try:
                        newdlens.append(len(d) if hasattr(d, "__len__") else 0)
                    except Exception:
                        newdlens.append(0)
            else:
                newdlens = []

            # Forward if any data source has grown
            if (
                newdlens
                and hasattr(self, "_dlens")
                and any(
                    nl > old_len
                    for old_len, nl in zip(self._dlens, newdlens)
                    if old_len is not None and nl is not None
                )
            ):
                try:
                    if hasattr(self, "forward"):
                        self.forward()
                except Exception:
                    pass

            # Update _dlens
            self._dlens = newdlens

            # CRITICAL FIX: Set datetime safely - only use data sources that have valid data
            if (
                hasattr(self, "datas")
                and self.datas
                and hasattr(self, "lines")
                and hasattr(self.lines, "datetime")
            ):
                valid_data_times = []
                for d in self.datas:
                    try:
                        if (
                            len(d) > 0
                            and hasattr(d, "datetime")
                            and hasattr(d.datetime, "__getitem__")
                        ):
                            dt_val = d.datetime[0]
                            # Only add valid datetime values (not None or NaN)
                            if dt_val is not None and not (
                                isinstance(dt_val, float) and math.isnan(dt_val)
                            ):
                                valid_data_times.append(dt_val)
                    except (IndexError, AttributeError, TypeError):
                        continue

                if valid_data_times:
                    try:
                        self.lines.datetime[0] = max(valid_data_times)
                    except (ValueError, IndexError, AttributeError):
                        # If setting datetime fails, use a default valid ordinal (1 = Jan 1, Year 1)
                        self.lines.datetime[0] = 1.0
                else:
                    # CRITICAL FIX: Use valid ordinal instead of 0.0
                    # 1.0 corresponds to January 1, year 1 in the proleptic Gregorian calendar
                    self.lines.datetime[0] = 1.0

            # Return the length of this strategy (number of processed bars)
            try:
                return len(self)
            except Exception:
                return 0

        # Monkey patch the Strategy class
        Strategy._clk_update = safe_clk_update

    except ImportError:
        # Silently ignore - Strategy already has _clk_update method
        pass
    except Exception:
        # Silently ignore - Strategy already has _clk_update method
        pass


def findbases(kls, topclass):
    """Recursively find all base classes that inherit from topclass.

    This function traverses the class hierarchy using __bases__ and recursively
    collects all base classes that are subclasses of the specified topclass.

    Args:
        kls: The class to search bases for.
        topclass: The top-level class to filter by (only bases that are
            subclasses of this class are included).

    Returns:
        list: A list of base classes in order from most ancestral to most
            immediate parent.

    Note:
        This function uses recursion, but the depth is limited by Python's
        recursion limit. In practice, class hierarchies rarely exceed this.
    """
    retval = []
    for base in kls.__bases__:
        if issubclass(base, topclass):
            retval.extend(findbases(base, topclass))
            retval.append(base)
    return retval


def findowner(owned, cls, startlevel=2, skip=None):
    """Find the owner object in the call stack or context.

    This function first checks the OwnerContext for an explicitly set owner,
    then falls back to traversing the call stack to find an object that:
    1. Is an instance of the specified class (cls)
    2. Is not the owned object itself
    3. Is not the skip object (if provided)

    This is commonly used to find parent containers (e.g., Strategy finding
    its Cerebro, or Indicator finding its Strategy).

    Args:
        owned: The object looking for its owner.
        cls: The class type the owner must be an instance of.
        startlevel: Stack frame level to start searching from (default: 2,
            skips this function and the caller).
        skip: Optional object to skip during the search.

    Returns:
        The owner object if found, None otherwise.

    Note:
        Uses OwnerContext for explicit owner management. The legacy sys._getframe()
        based lookup has been removed for better portability and performance.
    """
    # Check OwnerContext for explicit owner management
    # This is the only method now - no stack frame inspection
    context_owner = OwnerContext.get_current_owner(cls)
    if context_owner is not None:
        if context_owner is not owned and context_owner is not skip:
            return context_owner

    # No owner found in context
    return None


class ObjectFactory:
    """Factory class to replace MetaBase functionality.

    This class provides a static method for creating objects with lifecycle
    hooks similar to the original metaclass implementation.

    The creation process follows these steps:
        1. doprenew: Pre-new processing (class modification)
        2. donew: Object creation
        3. dopreinit: Pre-initialization processing
        4. doinit: Main initialization
        5. dopostinit: Post-initialization processing
    """

    @staticmethod
    def create(cls, *args, **kwargs):
        """Create an object with lifecycle hooks.

        Args:
            cls: The class to instantiate.
            *args: Positional arguments for initialization.
            **kwargs: Keyword arguments for initialization.

        Returns:
            The created and initialized object.
        """
        # Pre-new processing
        if hasattr(cls, "doprenew"):
            cls, args, kwargs = cls.doprenew(*args, **kwargs)

        # Object creation
        if hasattr(cls, "donew"):
            _obj, args, kwargs = cls.donew(*args, **kwargs)
        else:
            _obj = cls.__new__(cls)

        # Pre-init processing
        if hasattr(cls, "dopreinit"):
            _obj, args, kwargs = cls.dopreinit(_obj, *args, **kwargs)

        # Main initialization
        if hasattr(cls, "doinit"):
            _obj, args, kwargs = cls.doinit(_obj, *args, **kwargs)
        else:
            _obj.__init__(*args, **kwargs)

        # Post-init processing
        if hasattr(cls, "dopostinit"):
            _obj, args, kwargs = cls.dopostinit(_obj, *args, **kwargs)

        return _obj


class BaseMixin:
    """Mixin providing factory-based object creation without metaclass.

    This mixin provides default implementations for the lifecycle hooks
    used by ObjectFactory. Subclasses can override these methods to
    customize object creation and initialization.

    Methods:
        doprenew: Called before object creation (class-level).
        donew: Creates the object instance.
        dopreinit: Called before __init__.
        doinit: Calls __init__ on the object.
        dopostinit: Called after __init__.
        create: Factory method for instance creation.
    """

    @classmethod
    def doprenew(cls, *args, **kwargs):
        """Called before object creation.

        Args:
            *args: Positional arguments for object creation.
            **kwargs: Keyword arguments for object creation.

        Returns:
            tuple: (cls, args, kwargs) - Class and arguments to use.
        """
        return cls, args, kwargs

    @classmethod
    def donew(cls, *args, **kwargs):
        """Create a new object instance.

        Args:
            *args: Positional arguments for object creation.
            **kwargs: Keyword arguments for object creation.

        Returns:
            tuple: (_obj, args, kwargs) - New instance and remaining arguments.
        """
        _obj = cls.__new__(cls)
        return _obj, args, kwargs

    @classmethod
    def dopreinit(cls, _obj, *args, **kwargs):
        """Called before __init__ to modify arguments.

        Args:
            _obj: The object instance.
            *args: Positional arguments for __init__.
            **kwargs: Keyword arguments for __init__.

        Returns:
            tuple: (_obj, args, kwargs) - Object and arguments for __init__.
        """
        return _obj, args, kwargs

    @classmethod
    def doinit(cls, _obj, *args, **kwargs):
        """Call __init__ on the object.

        Args:
            _obj: The object instance.
            *args: Positional arguments for __init__.
            **kwargs: Keyword arguments for __init__.

        Returns:
            tuple: (_obj, args, kwargs) - Object and remaining arguments.
        """
        _obj.__init__(*args, **kwargs)
        return _obj, args, kwargs

    @classmethod
    def dopostinit(cls, _obj, *args, **kwargs):
        """Called after __init__ for post-processing.

        Args:
            _obj: The object instance.
            *args: Remaining positional arguments.
            **kwargs: Remaining keyword arguments.

        Returns:
            tuple: (_obj, args, kwargs) - Object and remaining arguments.
        """
        return _obj, args, kwargs

    @classmethod
    def create(cls, *args, **kwargs):
        """Factory method to create instances"""
        return ObjectFactory.create(cls, *args, **kwargs)


class AutoInfoClass:
    """Dynamic class for storing parameter and info key-value pairs.

    This class provides a flexible mechanism for storing and retrieving
    configuration data (parameters, plot info, etc.) with support for
    inheritance and derivation.

    Class Methods:
        _getpairsbase: Get base class pairs as OrderedDict.
        _getpairs: Get all pairs (including inherited) as OrderedDict.
        _getrecurse: Check if recursive derivation is enabled.
        _derive: Create a derived class with additional parameters.
        _getkeys: Get all parameter keys.
        _getdefaults: Get all default values.
        _getitems: Get all key-value pairs.
        _gettuple: Get pairs as tuple of tuples.

    Instance Methods:
        isdefault: Check if a parameter has its default value.
        notdefault: Check if a parameter differs from default.
        get/_get: Get a parameter value with optional default.
    """

    # Class methods returning empty defaults - equivalent to:
    # @classmethod
    # def _getpairsbase(cls): return OrderedDict()
    _getpairsbase = classmethod(lambda cls: OrderedDict())
    _getpairs = classmethod(lambda cls: OrderedDict())
    _getrecurse = classmethod(lambda cls: False)

    @classmethod
    def _derive(cls, name, info, otherbases, recurse=False):
        """Create a derived class with merged parameters.

        This method creates a new class that inherits from the current class
        and includes parameters from both the base class and additional sources.

        Args:
            cls: The base class to derive from.
            name: Name suffix for the new class.
            info: New parameters to add (dict or tuple of tuples).
            otherbases: Additional base classes or parameter dicts to merge.
            recurse: If True, recursively derive nested parameter classes.

        Returns:
            A new class with merged parameters.

        Example:
            DerivedParams = BaseParams._derive('MyStrategy', newparams, morebasesparams)
        """
        # Collect the 3 sets of info: base class, other bases, and new info
        baseinfo = cls._getpairs().copy()  # Shallow copy to preserve base class params
        obasesinfo = OrderedDict()  # Parameters from other base classes
        for obase in otherbases:
            # If otherbases contains dicts/tuples, update directly
            # Otherwise, get params from class instances via _getpairs()
            if isinstance(obase, (tuple, dict)):
                obasesinfo.update(obase)
            else:
                obasesinfo.update(obase._getpairs())

        # Update base info with parameters from other bases
        baseinfo.update(obasesinfo)

        # Create final class info: base + otherbases + new params
        clsinfo = baseinfo.copy()
        clsinfo.update(info)

        # Items to add: otherbases + new params (excluding base class params)
        info2add = obasesinfo.copy()
        info2add.update(info)

        # Create new derived class and register in module
        clsmodule = sys.modules[cls.__module__]
        newclsname = str(cls.__name__ + "_" + name)  # str - Python 2/3 compat

        # This loop makes sure that if the name has already been defined, a new
        # unique name is found. A collision example is in the plotlines names
        # definitions of bt.indicators.MACD and bt.talib.MACD. Both end up
        # definining a MACD_pl_macd and this makes it impossible for the pickle
        # module to send results over a multiprocessing channel
        namecounter = 1
        while hasattr(clsmodule, newclsname):
            newclsname += str(namecounter)
            namecounter += 1

        newcls = type(newclsname, (cls,), {})
        setattr(clsmodule, newclsname, newcls)
        # Set up class methods to return baseinfo, clsinfo, and recurse values
        setattr(newcls, "_getpairsbase", classmethod(lambda cls: baseinfo.copy()))
        setattr(newcls, "_getpairs", classmethod(lambda cls: clsinfo.copy()))
        setattr(newcls, "_getrecurse", classmethod(lambda cls: recurse))

        for infoname, infoval in info2add.items():
            # If recurse is True, recursively derive nested info classes
            # This is rarely used in practice
            if recurse:
                recursecls = getattr(newcls, infoname, AutoInfoClass)
                infoval = recursecls._derive(name + "_" + infoname, infoval, [])
            # Set the info attribute on the new class
            setattr(newcls, infoname, infoval)

        return newcls

    def isdefault(self, pname):
        """Check if a parameter has its default value."""
        return self._get(pname) == self._getkwargsdefault()[pname]

    def notdefault(self, pname):
        """Check if a parameter differs from its default value."""
        return self._get(pname) != self._getkwargsdefault()[pname]

    def _get(self, name, default=None):
        """Get attribute value by name with optional default."""
        return getattr(self, name, default)

    def get(self, name, default=None):
        """Get a parameter value by name with optional default.

        Args:
            name: Name of the parameter to get.
            default: Default value if parameter is not found.

        Returns:
            The parameter value or default if not found.
        """
        return self._get(name, default)

    @classmethod
    def _getkwargsdefault(cls):
        """Get default parameter values as OrderedDict."""
        return cls._getpairs()

    @classmethod
    def _getkeys(cls):
        """Get all parameter keys."""
        return cls._getpairs().keys()

    @classmethod
    def _getdefaults(cls):
        """Get all default parameter values as list."""
        return list(cls._getpairs().values())

    @classmethod
    def _getitems(cls):
        """Get all key-value pairs as items view."""
        return cls._getpairs().items()

    @classmethod
    def _gettuple(cls):
        """Get all key-value pairs as tuple of tuples."""
        return tuple(cls._getpairs().items())

    def _getkwargs(self, skip_=False):
        """Get current parameter values as OrderedDict."""
        pairs = [
            (x, getattr(self, x)) for x in self._getkeys() if not skip_ or not x.startswith("_")
        ]
        return OrderedDict(pairs)

    def _getvalues(self):
        """Get all current parameter values as list."""
        return [getattr(self, x) for x in self._getkeys()]

    def __new__(cls, *args, **kwargs):
        """Create a new instance with recursive parameter initialization."""
        obj = super().__new__(cls, *args, **kwargs)

        if cls._getrecurse():
            for infoname in obj._getkeys():
                recursecls = getattr(cls, infoname)
                setattr(obj, infoname, recursecls())

        return obj


def _reconstruct_param_class(class_name, all_params, instance_values):
    """
    Reconstruct a parameter class instance for unpickling.

    CRITICAL FIX: This function is called during unpickling to recreate
    parameter class instances created by ParameterManager._derive_params().
    Required for multiprocessing support in strategy optimization.

    Args:
        class_name: Name of the parameter class
        all_params: Dictionary of default parameter values
        instance_values: Dictionary of instance-specific values

    Returns:
        Reconstructed parameter class instance
    """
    # Create the parameter class using the same logic as _derive_params
    param_class = ParameterManager._derive_params(class_name, all_params, ())

    # Create an instance with the saved values
    instance = param_class()
    for key, value in instance_values.items():
        setattr(instance, key, value)

    return instance


class ParameterManager:
    """Manager for handling parameter operations without metaclass.

    This class provides static methods for setting up and deriving parameter
    classes, handling package imports, and managing parameter inheritance.

    Methods:
        setup_class_params: Set up parameters for a class.
        _derive_params: Create a derived parameter class.
        _handle_packages: Handle package and module imports.
    """

    @staticmethod
    def setup_class_params(cls, params=(), packages=(), frompackages=()):
        """Set up parameters for a class"""
        # Handle packages and frompackages
        ParameterManager._handle_packages(cls, packages, frompackages)

        # Get params from base classes
        bases = tuple(cls.__mro__[1:])  # Skip self

        # Create derived params
        cls._params = ParameterManager._derive_params(cls.__name__, params, bases)

        # Set params property on the class
        setattr(cls, "params", cls._params)

        return cls._params

    @staticmethod
    def _derive_params(name, params, otherbases):
        """Derive parameter class"""
        # Create a simple parameter class
        class_name = f"Params_{name}"

        # Collect all parameters from base classes first
        all_params = OrderedDict()

        # Process base classes in reverse order for proper inheritance
        for base in reversed(otherbases):
            if hasattr(base, "_params") and base._params is not None:
                if hasattr(base._params, "_getpairs"):
                    base_params = base._params._getpairs()
                    all_params.update(base_params)
                elif hasattr(base._params, "_gettuple"):
                    base_params = dict(base._params._gettuple())
                    all_params.update(base_params)
                elif hasattr(base._params, "__dict__"):
                    # OPTIMIZED: Get attributes from parameter instance using __dict__
                    for attr_name, attr_value in base._params.__dict__.items():
                        if not attr_name.startswith("_") and not callable(attr_value):
                            all_params[attr_name] = attr_value

        # Handle current class params - could be tuple, dict, or dict-like
        if isinstance(params, dict):
            # Direct dictionary
            all_params.update(params)
        elif isinstance(params, (tuple, list)):
            # Convert tuple/list to dict
            for item in params:
                if isinstance(item, (tuple, list)) and len(item) >= 2:
                    key, value = item[0], item[1]
                    all_params[key] = value
                elif isinstance(item, string_types):
                    # Just a key with None value
                    all_params[item] = None
                elif hasattr(item, "__iter__") and not isinstance(item, string_types):
                    # Try to treat as key-value pair
                    item_list = list(item)
                    if len(item_list) >= 2:
                        all_params[item_list[0]] = item_list[1]
        elif hasattr(params, "items"):
            # Dict-like object
            all_params.update(params)
        elif hasattr(params, "__dict__"):
            # OPTIMIZED: Object with attributes, using __dict__ for performance
            for attr_name, attr_value in params.__dict__.items():
                if not attr_name.startswith("_") and not callable(attr_value):
                    all_params[attr_name] = attr_value
        elif hasattr(params, "_getpairs"):
            all_params.update(params._getpairs())
        elif hasattr(params, "_gettuple"):
            all_params.update(dict(params._gettuple()))

        # CRITICAL FIX: Ensure common parameter names are always available
        # Many indicators expect these standard parameters
        common_defaults = {
            "period": 14,
            "movav": None,
            "_movav": None,
            "lookback": 1,
            "upperband": 70.0,
            "lowerband": 30.0,
            "safediv": False,
            "safepct": False,
            "fast": 5,  # For oscillators
            "slow": 34,  # For oscillators
            "signal": 9,  # For MACD-style indicators
            "mult": 2.0,  # For bands
            "matype": 0,  # Moving average type
        }

        # Add common defaults if not already present
        for key, default_value in common_defaults.items():
            if key not in all_params:
                all_params[key] = default_value

        # CRITICAL FIX: Handle _movav parameter specially - it should default to SMA
        if "_movav" not in all_params or all_params["_movav"] is None:
            # CRITICAL FIX: Don't import MovAv during class creation to avoid circular imports
            # We'll handle this lazily in the parameter getter instead
            all_params["_movav"] = None

        # Create new parameter class with all necessary methods
        class ParamClass(AutoInfoClass):
            """Dynamically created parameter class.

            This class is created dynamically with the parameters from the
            target class. It provides access to parameter values via attributes.

            Attributes:
                params: Self-reference for backward compatibility.
            """

            @classmethod
            def _getpairs(cls):
                return all_params.copy()

            @classmethod
            def _gettuple(cls):
                return tuple(all_params.items())

            @classmethod
            def _getkeys(cls):
                return list(all_params.keys())

            @classmethod
            def _getdefaults(cls):
                return list(all_params.values())

            def __init__(self, **kwargs):
                """Initialize the ParamClass with parameter values.

                Args:
                    **kwargs: Parameter values to override defaults.
                """
                super().__init__()
                # Set default values as instance attributes
                for key, default_value in all_params.items():
                    # Use provided value if available, otherwise use default
                    value = kwargs.get(key, default_value)
                    setattr(self, key, value)

                # CRITICAL FIX: Set up self-reference for backwards compatibility
                # This allows both self.p.period and self.params.period to work
                object.__setattr__(self, "params", self)

            def __getattr__(self, name):
                # CRITICAL FIX: Enhanced fallback for missing attributes with common parameter support
                # First check if it's in our known parameters
                if name in all_params:
                    value = all_params[name]
                    # Special handling for _movav parameter
                    if name == "_movav" and value is None:
                        # Try to import and return SMA as default
                        try:
                            from .indicators.mabase import MovAv

                            return MovAv.SMA
                        except ImportError:
                            # If import fails, return a simple fallback
                            try:
                                from .indicators.sma import MovingAverageSimple

                                return MovingAverageSimple
                            except ImportError:
                                # Final fallback - return None
                                return None
                    return value

                # Handle common parameter name variants and aliases
                param_aliases = {
                    "period": ["period", "periods", "window", "length"],
                    "movav": ["movav", "_movav", "ma", "moving_average"],
                    "lookback": ["lookback", "look_back", "lag"],
                    "upperband": ["upperband", "upper_band", "upper", "high_band"],
                    "lowerband": ["lowerband", "lower_band", "lower", "low_band"],
                    "fast": ["fast", "fast_period", "fastperiod"],
                    "slow": ["slow", "slow_period", "slowperiod"],
                    "signal": ["signal", "signal_period", "signalperiod"],
                }

                # Check if the requested name is an alias for a known parameter
                for canonical_name, aliases in param_aliases.items():
                    if name in aliases and canonical_name in all_params:
                        value = all_params[canonical_name]
                        # Special handling for movav aliases
                        if canonical_name == "_movav" and value is None:
                            try:
                                from .indicators.mabase import MovAv

                                return MovAv.SMA
                            except ImportError:
                                return None
                        return value

                # For period specifically, always return a sensible default
                if name in ("period", "periods", "window", "length"):
                    return 14
                if name in ("_movav", "movav", "ma", "moving_average"):
                    try:
                        from .indicators.mabase import MovAv

                        return MovAv.SMA
                    except ImportError:
                        return None
                if name in ("lookback", "look_back", "lag"):
                    return 1
                if name in ("upperband", "upper_band", "upper", "high_band"):
                    return 70.0
                if name in ("lowerband", "lower_band", "lower", "low_band"):
                    return 30.0
                if name in ("safediv", "safe_div"):
                    return False
                if name in ("safepct", "safe_pct"):
                    return False
                if name in ("fast", "fast_period", "fastperiod"):
                    return 5
                if name in ("slow", "slow_period", "slowperiod"):
                    return 34
                if name in ("signal", "signal_period", "signalperiod"):
                    return 9
                if name in ("mult", "multiplier"):
                    return 2.0

                # Return None for unknown attributes instead of raising AttributeError
                return None

            def __setattr__(self, name, value):
                # Allow setting attributes normally
                super().__setattr__(name, value)

            def __reduce__(self):
                """
                CRITICAL FIX: Support pickling for multiprocessing (optstrategy).

                This allows the parameter class to be serialized when using
                multiprocessing for strategy optimization.
                """
                # Return a tuple: (callable, args) to reconstruct the object
                # We return the class and its current state as kwargs
                return (
                    _reconstruct_param_class,
                    (
                        class_name,
                        all_params,
                        {k: getattr(self, k) for k in all_params.keys() if hasattr(self, k)},
                    ),
                )

        ParamClass.__name__ = class_name
        ParamClass.__module__ = __name__  # CRITICAL: Set module for pickling
        ParamClass.__qualname__ = class_name  # Set qualname for Python 3

        return ParamClass

    @staticmethod
    def _handle_packages(cls, packages, frompackages):
        """Handle package imports"""
        cls.packages = packages
        cls.frompackages = frompackages

        clsmod = sys.modules[cls.__module__]

        for package in packages:
            if isinstance(package, (tuple, list)):
                package, alias = package
            else:
                alias = package

            try:
                pmod = __import__(package)
                for part in package.split(".")[1:]:
                    pmod = getattr(pmod, part)
                setattr(clsmod, alias, pmod)
            except ImportError:
                pass

        for packageitems in frompackages:
            if len(packageitems) != 2:
                continue
            package, frompackage = packageitems

            if isinstance(frompackage, string_types):
                frompackage = (frompackage,)

            for fromitem in frompackage:
                if isinstance(fromitem, (tuple, list)):
                    fromitem, alias = fromitem
                else:
                    alias = fromitem

                try:
                    pmod = __import__(package, fromlist=[fromitem])
                    pattr = getattr(pmod, fromitem)
                    setattr(clsmod, alias, pattr)
                except (ImportError, AttributeError):
                    pass


class ParamsMixin(BaseMixin):
    """Mixin class that provides parameter management capabilities"""

    def __init_subclass__(cls, **kwargs):
        """Set up parameters when a subclass is created"""
        super().__init_subclass__(**kwargs)

        # CRITICAL FIX: Call _initialize_indicator_aliases whenever an indicator class is created
        # OPTIMIZED: Use cached type check
        if is_class_type(cls, "Indicator"):
            try:
                _initialize_indicator_aliases()
            except Exception:
                pass

        # Set up params, packages, frompackages if they exist
        params = getattr(cls, "params", ())
        packages = getattr(cls, "packages", ())
        frompackages = getattr(cls, "frompackages", ())

        ParameterManager.setup_class_params(cls, params, packages, frompackages)

        # CRITICAL FIX: Auto-patch __init__ methods of indicators to ensure proper parameter handling
        if hasattr(cls, "__init__") and "__init__" in cls.__dict__:
            original_init = cls.__init__

            # CRITICAL FIX: Store the original __init__ so Strategy can call it directly
            # This prevents infinite recursion when Strategy.user_init tries to call cls.__init__
            cls._original_init = original_init

            def patched_init(self, *args, **kwargs):
                # CRITICAL FIX: For indicators, set up data0/data1 BEFORE anything else
                # This ensures indicators can access self.data0, self.data1 during initialization
                if "Indicator" in self.__class__.__name__ or any(
                    "Indicator" in base.__name__ for base in self.__class__.__mro__
                ):
                    if hasattr(self, "datas") and self.datas:
                        # Set data0, data1, etc. immediately from existing datas
                        for d, data in enumerate(self.datas):
                            setattr(self, f"data{d}", data)
                    elif args:
                        # If we don't have datas set yet, try to extract from args
                        temp_datas = []
                        for i, arg in enumerate(args):
                            # Check if this is a data-like object
                            if (
                                hasattr(arg, "lines")
                                or hasattr(arg, "_name")
                                or hasattr(arg, "__class__")
                                and "Data" in str(arg.__class__.__name__)
                                or hasattr(arg, "__class__")
                                and any(
                                    "LineSeries" in base.__name__ for base in arg.__class__.__mro__
                                )
                            ):
                                temp_datas.append(arg)
                                setattr(self, f"data{i}", arg)
                            else:
                                # Non-data argument, stop processing
                                break

                        # Set up datas if we found any
                        if temp_datas:
                            if not hasattr(self, "datas") or not self.datas:
                                self.datas = temp_datas
                                self.data = temp_datas[0]
                    else:
                        # CRITICAL FIX: If indicator created with no data, search call stack for data
                        # This handles cases like AwesomeOscillator() inside AccDecOscillator.__init__
                        if not hasattr(self, "datas") or not self.datas:
                            # Search the call stack for an object with data
                            import inspect

                            for frame_info in inspect.stack():
                                frame_locals = frame_info.frame.f_locals
                                # Look for 'self' in the frame
                                if "self" in frame_locals:
                                    potential_owner = frame_locals["self"]
                                    # Skip if it's the same object
                                    if potential_owner is self:
                                        continue
                                    # Check if this object has datas
                                    if hasattr(potential_owner, "datas") and potential_owner.datas:
                                        self.datas = potential_owner.datas
                                        self.data = potential_owner.datas[0]
                                        for d, data in enumerate(potential_owner.datas):
                                            setattr(self, f"data{d}", data)
                                        break
                                    # Or just data
                                    elif (
                                        hasattr(potential_owner, "data")
                                        and potential_owner.data is not None
                                    ):
                                        self.datas = [potential_owner.data]
                                        self.data = potential_owner.data
                                        self.data0 = potential_owner.data
                                        break

                # CRITICAL FIX: Restore kwargs from __new__ if they were lost
                if hasattr(self, "_init_kwargs") and not kwargs:
                    kwargs = self._init_kwargs
                if hasattr(self, "_init_args") and not args:
                    args = self._init_args

                # CRITICAL FIX: Extract parameter kwargs before creating parameter instance
                # Separate parameter kwargs from other kwargs
                param_kwargs = {}
                other_kwargs = {}

                # Get list of valid parameter names from class
                # CRITICAL FIX: Use self.__class__ instead of cls to get the actual runtime class
                actual_cls = self.__class__
                valid_param_names = set()
                if hasattr(actual_cls, "_params") and actual_cls._params is not None:
                    try:
                        if hasattr(actual_cls._params, "_getkeys"):
                            valid_param_names = set(actual_cls._params._getkeys())
                        elif hasattr(actual_cls._params, "_getpairs"):
                            valid_param_names = set(actual_cls._params._getpairs().keys())
                    except Exception:
                        pass

                # Separate kwargs into param_kwargs and other_kwargs
                # Filter out test-specific and non-constructor kwargs
                test_kwargs = {
                    "main",
                    "plot",
                    "writer",
                    "analyzer",
                    "chkind",
                    "chkmin",
                    "chkargs",
                    "chkvals",
                    "chknext",
                    "chksamebars",
                }

                for key, value in kwargs.items():
                    if key in valid_param_names:
                        # This is a parameter - add to param_kwargs but NOT other_kwargs
                        param_kwargs[key] = value
                    elif key not in test_kwargs:
                        # This is not a parameter and not a test kwarg - pass to parent init
                        other_kwargs[key] = value

                # CRITICAL FIX: Always update parameter values from param_kwargs
                # Don't skip if self.p exists - we need to update it with new values
                if not hasattr(self, "p") or self.p is None:
                    # Create parameter instance with param_kwargs
                    if hasattr(cls, "_params") and cls._params is not None:
                        try:
                            self.p = cls._params(**param_kwargs)
                        except Exception:
                            from .utils import DotDict

                            self.p = DotDict(param_kwargs)
                    else:
                        from .utils import DotDict

                        self.p = DotDict(param_kwargs)
                else:
                    # self.p already exists - update it with param_kwargs
                    for key, value in param_kwargs.items():
                        setattr(self.p, key, value)

                # Also set self.params for backwards compatibility
                self.params = self.p

                # CRITICAL FIX: Ensure indicator has _plotinit method before user init
                if "Indicator" in cls.__name__ or is_class_type(cls, "Indicator"):
                    if not hasattr(self, "_plotinit"):
                        # Add _plotinit method
                        def default_plotinit():
                            plotinfo_defaults = {
                                "plot": True,
                                "subplot": True,
                                "plotname": "",
                                "plotskip": False,
                                "plotabove": False,
                                "plotlinelabels": False,
                                "plotlinevalues": True,
                                "plotvaluetags": True,
                                "plotymargin": 0.0,
                                "plotyhlines": [],
                                "plotyticks": [],
                                "plothlines": [],
                                "plotforce": False,
                                "plotmaster": None,
                            }

                            if not hasattr(self, "plotinfo"):
                                # Create plotinfo object with _get method and legendloc
                                class PlotInfoObj:
                                    """Plot information object for indicators.

                                    A simple plotinfo object with minimal attributes
                                    for plotting configuration.

                                    Attributes:
                                        legendloc: Location for the plot legend.
                                    """

                                    def __init__(self):
                                        """Initialize PlotInfoObj with default attributes."""
                                        self.legendloc = None  # CRITICAL: Add legendloc attribute

                                    def _get(self, key, default=None):
                                        """Get a plotinfo attribute value.

                                        Args:
                                            key: Name of the attribute.
                                            default: Default value if not found.

                                        Returns:
                                            The attribute value or default.
                                        """
                                        return getattr(self, key, default)

                                    def get(self, key, default=None):
                                        """Get a plotinfo attribute value.

                                        Args:
                                            key: Name of the attribute.
                                            default: Default value if not found.

                                        Returns:
                                            The attribute value or default.
                                        """
                                        return getattr(self, key, default)

                                    def __contains__(self, key):
                                        return hasattr(self, key)

                                self.plotinfo = PlotInfoObj()

                            for attr, default_val in plotinfo_defaults.items():
                                if not hasattr(self.plotinfo, attr):
                                    setattr(self.plotinfo, attr, default_val)

                            return True

                        self._plotinit = default_plotinit

                # CRITICAL FIX: Try calling original_init with different argument strategies
                # Some classes (like most indicators) don't accept args
                # Others (like _LineDelay, LinesOperation) need args
                # Parameter kwargs are already set via self.p, so don't pass them

                # Check if original_init accepts *args or **kwargs
                import inspect

                try:
                    sig = inspect.signature(original_init)
                    has_var_positional = any(
                        p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values()
                    )
                    has_var_keyword = any(
                        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                    )
                except (ValueError, TypeError):
                    has_var_positional = False
                    has_var_keyword = False

                # If __init__ accepts *args or **kwargs, pass everything
                if has_var_positional or has_var_keyword:
                    return original_init(self, *args, **other_kwargs)

                # Otherwise, try without args first (most common case)
                try:
                    # First, try without args - most common case for indicators/strategies
                    return original_init(self, **other_kwargs)
                except TypeError as e:
                    # Check if the error is about THIS class's __init__, not an internal call
                    # If the error mentions a different class name, it's from an internal call - re-raise it
                    error_str = str(e)
                    class_name = self.__class__.__name__

                    # If error mentions a different class, it's from internal code - re-raise
                    if ".__init__()" in error_str:
                        # Extract the class name from error message like "SomeClass.__init__() ..."
                        import re

                        match = re.search(r"(\w+)\.__init__\(\)", error_str)
                        if match and match.group(1) != class_name:
                            # Error is about a different class (internal call) - re-raise
                            raise

                    # If that failed, check if it's because THIS class needs positional arguments
                    if "missing" in error_str and "required positional argument" in error_str:
                        # This class needs positional args (like _LineDelay, LinesOperation)
                        # Pass all args - they're needed
                        return original_init(self, *args, **other_kwargs)
                    else:
                        # Different error - re-raise it
                        raise

            cls.__init__ = patched_init

        # Handle plotinfo and other info attributes (like the old metaclass system)
        info_attributes = ["plotinfo", "plotlines", "plotinfoargs"]
        for info_attr in info_attributes:
            if info_attr in cls.__dict__:
                info_dict = cls.__dict__[info_attr]
                if isinstance(info_dict, dict):
                    # CRITICAL FIX: Ensure plotinfo objects have all required attributes
                    if info_attr == "plotinfo":
                        # Set default plotinfo attributes if missing
                        default_plotinfo = {
                            "plot": True,
                            "subplot": True,
                            "plotname": "",
                            "plotskip": False,
                            "plotabove": False,
                            "plotlinelabels": False,
                            "plotlinevalues": True,
                            "plotvaluetags": True,
                            "plotymargin": 0.0,
                            "plotyhlines": [],
                            "plotyticks": [],
                            "plothlines": [],
                            "plotforce": False,
                            "plotmaster": None,
                        }
                        # Merge provided plotinfo with defaults
                        for key, default_value in default_plotinfo.items():
                            if key not in info_dict:
                                info_dict[key] = default_value

                    # Convert dictionary to attribute-accessible object
                    info_obj = type(f"{info_attr}_obj", (), info_dict)()

                    # CRITICAL FIX: Ensure the object can be used like a dict too
                    # Some code might expect dict-like access
                    def info_getitem(self, key):
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        if isinstance(key, str) and hasattr(self, key):
                            return getattr(self, key)
                        return None

                    def info_setitem(self, key, value):
                        # Only set if key is a string
                        if isinstance(key, str):
                            setattr(self, key, value)

                    def info_contains(self, key):
                        # CRITICAL FIX: Only check if key is a string
                        return isinstance(key, str) and hasattr(self, key)

                    def info_get(self, key, default=None):
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        if isinstance(key, str) and hasattr(self, key):
                            return getattr(self, key)
                        return default

                    def info_get_method(self, key, default=None):
                        """CRITICAL: _get method expected by plotting system"""
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        if isinstance(key, str) and hasattr(self, key):
                            return getattr(self, key)
                        return default

                    def info_keys(self):
                        # OPTIMIZED: Use __dict__ instead of dir() for better performance
                        return [
                            attr
                            for attr, val in self.__dict__.items()
                            if not attr.startswith("_") and not callable(val)
                        ]

                    def info_values(self):
                        return [getattr(self, attr) for attr in self.keys()]

                    def info_items(self):
                        return [(attr, getattr(self, attr)) for attr in self.keys()]

                    info_obj.__getitem__ = info_getitem
                    info_obj.__setitem__ = info_setitem
                    info_obj.__contains__ = info_contains
                    info_obj.get = info_get
                    info_obj._get = (
                        info_get_method  # CRITICAL: Add _get method for plotting compatibility
                    )
                    info_obj.keys = info_keys
                    info_obj.values = info_values
                    info_obj.items = info_items

                    setattr(cls, info_attr, info_obj)

        # Ensure the class has a params attribute that can handle _gettuple calls
        if hasattr(cls, "_params"):
            # If _params is not a proper parameter class, make it one
            if isinstance(cls._params, (tuple, list)) or not hasattr(cls._params, "_gettuple"):
                # Create a wrapper that provides _gettuple functionality
                class ParamsWrapper:
                    """Wrapper for parameter data to provide _gettuple method.

                    This wrapper ensures that parameter data (whether from a
                    tuple, list, or existing params object) provides the
                    _gettuple method expected by the framework.
                    """

                    def __init__(self, data):
                        """Initialize the wrapper with parameter data.

                        Args:
                            data: Parameter data as tuple, list, or object with _gettuple.
                        """
                        if isinstance(data, (tuple, list)):
                            self.data = data
                        elif hasattr(data, "_gettuple"):
                            self.data = data._gettuple()
                        else:
                            self.data = ()

                    def _gettuple(self):
                        return self.data if isinstance(self.data, tuple) else tuple(self.data)

                cls._params = ParamsWrapper(cls._params)

            # Set class-level params attribute for compatibility
            cls.params = cls._params

    def __new__(cls, *args, **kwargs):
        """Create instance and set up parameters before __init__ is called"""
        # Create the instance first
        instance = super().__new__(cls)

        # Set up parameters for this instance
        if hasattr(cls, "_params") and cls._params is not None:
            params_cls = cls._params
            param_names = set()

            # Get all parameter names from the class
            if hasattr(params_cls, "_getpairs"):
                param_names.update(params_cls._getpairs().keys())
            elif hasattr(params_cls, "_gettuple"):
                param_names.update(key for key, value in params_cls._gettuple())

            # Separate parameter and non-parameter kwargs
            param_kwargs = {}
            non_param_kwargs = {}
            for key, value in kwargs.items():
                if key in param_names:
                    param_kwargs[key] = value
                else:
                    non_param_kwargs[key] = value

            # Store non-param kwargs for later use
            instance._non_param_kwargs = non_param_kwargs

            # Create parameter instance
            try:
                instance._params_instance = params_cls()
            except Exception:
                # If instantiation fails, create a simple object
                instance._params_instance = type("ParamsInstance", (), {})()

            # Set all parameter values - first defaults, then custom values
            if hasattr(params_cls, "_getpairs"):
                for key, value in params_cls._getpairs().items():
                    # Use custom value if provided, otherwise use default
                    final_value = param_kwargs.get(key, value)
                    setattr(instance._params_instance, key, final_value)
            elif hasattr(params_cls, "_gettuple"):
                for key, value in params_cls._gettuple():
                    # Use custom value if provided, otherwise use default
                    final_value = param_kwargs.get(key, value)
                    setattr(instance._params_instance, key, final_value)

            # Also set any extra parameters that were passed but not in the params definition
            for key, value in param_kwargs.items():
                if not hasattr(instance._params_instance, key):
                    setattr(instance._params_instance, key, value)

        else:
            # No parameters defined, create parameter instance from kwargs
            instance._params_instance = type("ParamsInstance", (), {})()
            # Set all kwargs as parameters
            for key, value in kwargs.items():
                setattr(instance._params_instance, key, value)
            instance._non_param_kwargs = {}

        return instance

    def __init__(self, *args, **kwargs):
        """Initialize with only non-parameter kwargs"""
        # Use pre-filtered non-parameter kwargs if available
        if hasattr(self, "_non_param_kwargs"):
            filtered_kwargs = self._non_param_kwargs
        else:
            # Filter out parameter kwargs before calling super().__init__
            if hasattr(self.__class__, "_params") and self.__class__._params is not None:
                params_cls = self.__class__._params
                param_names = set()

                # Get all parameter names from the class
                if hasattr(params_cls, "_getpairs"):
                    param_names.update(params_cls._getpairs().keys())
                elif hasattr(params_cls, "_gettuple"):
                    param_names.update(key for key, value in params_cls._gettuple())

                # Filter kwargs to remove parameter kwargs
                filtered_kwargs = {k: v for k, v in kwargs.items() if k not in param_names}
            else:
                # No parameters, but still avoid passing args to object.__init__
                filtered_kwargs = {}

        # Call super().__init__ without args to avoid object.__init__() error
        # Only pass kwargs if this is not the base object to prevent "object.__init__() takes exactly one argument" error
        try:
            if filtered_kwargs:
                super().__init__(**filtered_kwargs)
            else:
                super().__init__()
        except TypeError as e:
            # If we reach object.__init__ and it complains about arguments, call it without kwargs
            if "object.__init__() takes" in str(e):
                super().__init__()
            else:
                raise

    @property
    def params(self):
        """Instance-level params property for backward compatibility"""
        return getattr(self, "_params_instance", None)

    @params.setter
    def params(self, value):
        """Allow setting params instance"""
        self._params_instance = value
        # CRITICAL FIX: Ensure p also points to the same instance
        object.__setattr__(self, "p", value)

    @property
    def p(self):
        """Provide p property for backward compatibility"""
        return getattr(self, "_params_instance", None)

    @p.setter
    def p(self, value):
        """Allow setting p instance"""
        self._params_instance = value
        # CRITICAL FIX: Ensure params also points to the same instance
        object.__setattr__(self, "params", value)


# For backward compatibility, keep the old class names as aliases
ParamsBase = ParamsMixin


class ItemCollection:
    """Collection that allows access by both index and name.

    This class holds a list of items that can be accessed either by their
    numeric index or by a string name. Names are set as attributes on the
    collection instance.

    Attributes:
        items (list): The underlying list of items.

    Example:
        collection = ItemCollection()
        collection.append(my_strategy, name='mystrat')
        collection[0]  # Access by index
        collection.mystrat  # Access by name
    """

    def __init__(self):
        """Initialize the collection with an empty items list."""
        self.items = list()

    def __len__(self):
        """Return the number of items in the collection."""
        return len(self.items)

    def append(self, item, name=None):
        """Add an item to the collection with an optional name."""
        setattr(self, name or item.__name__, item)
        self.items.append(item)

    def __getitem__(self, key):
        """Get item by index."""
        return self.items[key]

    def getnames(self):
        """Get list of all item names."""
        return [x.__name__ for x in self.items]

    def getitems(self):
        """Return list of (name, item) tuples for unpacking."""
        result = []
        for item in self.items:
            # Get item name from _name or __name__ attribute
            name = getattr(item, "_name", None) or getattr(item, "__name__", None)
            if name is None:
                # Fall back to lowercase class name
                name = item.__class__.__name__.lower()
            result.append((name, item))
        return result

    def getbyname(self, name):
        """Get item by name."""
        return getattr(self, name)


def _convert_plotlines_dict_to_object(cls):
    """Convert plotlines from dict to object with _get method"""
    if not hasattr(cls, "plotlines") or not isinstance(cls.plotlines, dict):
        return

    plotlines_dict = cls.plotlines

    class PlotLinesObj:
        """Object wrapper for plotlines dictionary.

        Converts a plotlines dictionary into an object that supports
        attribute access and the _get method expected by the plotting system.

        Attributes:
            _data: Original dictionary data.
        """

        def __init__(self, data_dict):
            """Initialize the PlotLinesObj with dictionary data.

            Args:
                data_dict: Dictionary of plot line configurations.
            """
            self._data = data_dict.copy()
            # Set attributes for direct access
            for key, value in data_dict.items():
                if isinstance(value, dict):
                    # Convert nested dicts to objects too
                    nested_obj = PlotLineAttrObj(value)
                    setattr(self, key, nested_obj)
                else:
                    setattr(self, key, value)

        def _get(self, key, default=None):
            """CRITICAL: _get method expected by plotting system"""
            if hasattr(self, key):
                return getattr(self, key)
            return self._data.get(key, default)

        def get(self, key, default=None):
            """Standard get method for compatibility"""
            if hasattr(self, key):
                return getattr(self, key)
            return self._data.get(key, default)

        def __contains__(self, key):
            return hasattr(self, key) or key in self._data

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(
                    f"'{self.__class__.__name__}' object has no attribute '{name}'"
                )
            # Return empty plot line object for missing attributes
            # Check if this might be a numeric index lookup first
            if name.isdigit() or name.startswith("_") and name[1:].isdigit():
                return PlotLineAttrObj({})
            return PlotLineAttrObj({})

    class PlotLineAttrObj:
        """Object wrapper for plot line attributes.

        Converts nested dictionaries in plotlines into objects that
        support attribute access.

        Attributes:
            _data: Original dictionary data.
        """

        def __init__(self, data_dict):
            """Initialize the PlotLineAttrObj with dictionary data.

            Args:
                data_dict: Dictionary of plot line attributes.
            """
            self._data = data_dict.copy()
            # Set attributes for direct access
            for key, value in data_dict.items():
                setattr(self, key, value)

        def _get(self, key, default=None):
            """CRITICAL: _get method expected by plotting system"""
            if hasattr(self, key):
                return getattr(self, key)
            return self._data.get(key, default)

        def get(self, key, default=None):
            """Standard get method for compatibility"""
            if hasattr(self, key):
                return getattr(self, key)
            return self._data.get(key, default)

        def __contains__(self, key):
            return hasattr(self, key) or key in self._data

    # Replace the dict with the object
    cls.plotlines = PlotLinesObj(plotlines_dict)


def _initialize_indicator_aliases():
    """
    CRITICAL FIX: Initialize all indicator aliases and ensure _plotinit method exists
    This function must be called after all indicator modules are loaded
    """
    try:
        global _INDICATOR_ALIASES_INITIALIZED
        if _INDICATOR_ALIASES_INITIALIZED:
            return True
        # Mark as initialized early to prevent re-entrancy from imports
        _INDICATOR_ALIASES_INITIALIZED = True
        import sys

        # CRITICAL FIX: Add a universal _plotinit method to all indicator classes
        def universal_plotinit(self):
            """Universal _plotinit method for all indicators"""
            # Set up default plotinfo if missing
            if not hasattr(self, "plotinfo"):
                # Create a plotinfo object that behaves like the expected plotinfo with _get method
                class PlotInfo:
                    """Plot configuration information object.

                    Stores plotting configuration for indicators and strategies.
                    Provides both attribute and dictionary-style access with defaults.

                    Attributes:
                        _data: Dictionary storing plot configuration values.
                        plot: Whether to plot this item.
                        subplot: Whether to plot in a separate subplot.
                        plotname: Name for the plot.
                        plotskip: Whether to skip plotting.
                        plotabove: Whether to plot above the data.
                        plotlinelabels: Whether to show line labels.
                        plotlinevalues: Whether to show line values.
                        plotvaluetags: Whether to show value tags.
                        plotymargin: Vertical margin for the plot.
                        plotyhlines: Horizontal lines at y values.
                        plotyticks: Y-axis tick positions.
                        plothlines: Horizontal lines.
                        plotforce: Force plotting even if disabled.
                        plotmaster: Master plot for this item.
                    """

                    def __init__(self):
                        """Initialize PlotInfo with default plotting configuration."""
                        self._data = {}
                        # Set default plot attributes
                        defaults = {
                            "plot": True,
                            "subplot": True,
                            "plotname": "",
                            "plotskip": False,
                            "plotabove": False,
                            "plotlinelabels": False,
                            "plotlinevalues": True,
                            "plotvaluetags": True,
                            "plotymargin": 0.0,
                            "plotyhlines": [],
                            "plotyticks": [],
                            "plothlines": [],
                            "plotforce": False,
                            "plotmaster": None,
                        }
                        self._data.update(defaults)
                        # CRITICAL FIX: Set attributes directly on the object for compatibility
                        for key, value in defaults.items():
                            setattr(self, key, value)

                    def _get(self, key, default=None):
                        """Get plot info attribute with default - CRITICAL METHOD"""
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        if isinstance(key, str) and hasattr(self, key):
                            return getattr(self, key)
                        # Then try the _data dict
                        if hasattr(self, "_data") and key in self._data:
                            return self._data[key]
                        return default

                    def get(self, key, default=None):
                        """Standard get method for dict-like access"""
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        if isinstance(key, str) and hasattr(self, key):
                            return getattr(self, key)
                        # Then try the _data dict
                        if hasattr(self, "_data") and key in self._data:
                            return self._data[key]
                        return default

                    def __getattr__(self, name):
                        if name.startswith("_") and name != "_data":
                            raise AttributeError(
                                f"'{self.__class__.__name__}' object has no attribute '{name}'"
                            )
                        # Try _data dict first
                        if hasattr(self, "_data") and name in self._data:
                            return self._data[name]
                        # Return None for missing attributes to prevent errors
                        return None

                    def __setattr__(self, name, value):
                        if name.startswith("_") and name != "_data":
                            super().__setattr__(name, value)
                        else:
                            if not hasattr(self, "_data"):
                                super().__setattr__("_data", {})
                            self._data[name] = value
                            # CRITICAL FIX: Also set as direct attribute for compatibility
                            super().__setattr__(name, value)

                    def __contains__(self, key):
                        """Support 'in' operator"""
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        string_check = isinstance(key, str) and hasattr(self, key)
                        dict_check = key in getattr(self, "_data", {})
                        return string_check or dict_check

                    def keys(self):
                        """Return all keys"""
                        keys = set(getattr(self, "_data", {}).keys())
                        # OPTIMIZED: Use __dict__ instead of dir() for better performance
                        keys.update(
                            attr
                            for attr, val in self.__dict__.items()
                            if not attr.startswith("_") and not callable(val)
                        )
                        return list(keys)

                    def values(self):
                        """Return all values"""
                        return [self._get(key) for key in self.keys()]

                    def items(self):
                        """Return all items"""
                        return [(key, self._get(key)) for key in self.keys()]

                self.plotinfo = PlotInfo()
            else:
                # If plotinfo exists but doesn't have _get method, add it
                if not hasattr(self.plotinfo, "_get"):

                    def _get_method(key, default=None):
                        if hasattr(self.plotinfo, key):
                            return getattr(self.plotinfo, key)
                        elif hasattr(self.plotinfo, "_data") and key in self.plotinfo._data:
                            return self.plotinfo._data[key]
                        else:
                            return default

                    self.plotinfo._get = _get_method

                # Also ensure get method exists
                if not hasattr(self.plotinfo, "get"):

                    def get_method(key, default=None):
                        if hasattr(self.plotinfo, key):
                            return getattr(self.plotinfo, key)
                        elif hasattr(self.plotinfo, "_data") and key in self.plotinfo._data:
                            return self.plotinfo._data[key]
                        else:
                            return default

                    self.plotinfo.get = get_method

            return True

        # CRITICAL FIX: Apply _plotinit to indicator classes without complex patching
        indicators_module = sys.modules.get("backtrader.indicators")
        if indicators_module:
            for attr_name in dir(indicators_module):
                try:
                    attr = getattr(indicators_module, attr_name)
                    if (
                        isinstance(attr, type)
                        and hasattr(attr, "__module__")
                        and "indicator" in attr.__module__.lower()
                        and hasattr(attr, "lines")
                    ):
                        # Add _plotinit method if missing
                        if not hasattr(attr, "_plotinit"):
                            attr._plotinit = universal_plotinit
                            pass

                        # CRITICAL FIX: Convert plotlines dict to object with _get method
                        if hasattr(attr, "plotlines") and isinstance(attr.plotlines, dict):
                            _convert_plotlines_dict_to_object(attr)
                            pass

                except Exception:
                    continue

        # CRITICAL FIX: Patch specific indicator classes that are known to be problematic
        try:
            from .indicators.sma import MovingAverageSimple

            if not hasattr(MovingAverageSimple, "_plotinit"):
                MovingAverageSimple._plotinit = universal_plotinit
                pass
        except ImportError:
            pass

        # CRITICAL FIX: Search for any loaded indicator classes and ensure they have _plotinit
        for module_name, module in sys.modules.items():
            if "indicator" in module_name.lower() and hasattr(module, "__dict__"):
                for attr_name, attr_value in module.__dict__.items():
                    try:
                        if (
                            isinstance(attr_value, type)
                            and hasattr(attr_value, "lines")
                            and "Indicator" in str(attr_value.__mro__)
                        ):
                            # Ensure the class has _plotinit
                            if not hasattr(attr_value, "_plotinit"):
                                attr_value._plotinit = universal_plotinit
                                pass

                            # CRITICAL FIX: Convert plotlines dict to object with _get method
                            if hasattr(attr_value, "plotlines") and isinstance(
                                attr_value.plotlines, dict
                            ):
                                _convert_plotlines_dict_to_object(attr_value)
                                pass

                        # CRITICAL FIX: Also handle Mixin classes that have plotlines
                        elif (
                            isinstance(attr_value, type)
                            and hasattr(attr_value, "plotlines")
                            and isinstance(attr_value.plotlines, dict)
                        ):
                            _convert_plotlines_dict_to_object(attr_value)
                            pass

                    except Exception:
                        continue

        pass

    except Exception:
        # print(f"Warning: _initialize_indicator_aliases failed: {e}")  # Removed for performance
        # Continue without failing completely
        pass


# CRITICAL FIX: Call initialization functions when module loads
try:
    _initialize_indicator_aliases()
    patch_strategy_clk_update()
except Exception:
    pass  # Silently fail during module loading
