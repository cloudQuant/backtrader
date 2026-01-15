#!/usr/bin/env python
"""Backtrader Indicator Module.

This module provides the base Indicator class and related infrastructure
for creating and managing technical analysis indicators. It replaces the
metaclass-based approach with explicit inheritance and registration.

The Indicator class serves as the foundation for all technical indicators
in backtrader, managing line data, minimum periods, and calculation logic.
"""
from .lineiterator import IndicatorBase, LineIterator
from .lineseries import Lines
from .metabase import AutoInfoClass
from .utils.py3 import range


class IndicatorRegistry:
    """Registry to manage indicator classes and provide caching functionality.

    This class replaces the metaclass-based indicator registration and
    caching mechanism from the original backtrader implementation.
    """

    _indcol = dict()
    _icache = dict()
    _icacheuse = False

    @classmethod
    def register(cls, name, indicator_cls):
        """Register an indicator class in the registry.

        Args:
            name: Name of the indicator class
            indicator_cls: The indicator class to register
        """
        if not name.startswith("_") and name != "Indicator":
            cls._indcol[name] = indicator_cls

    @classmethod
    def cleancache(cls):
        """Clear the indicator cache."""
        cls._icache = dict()

    @classmethod
    def usecache(cls, onoff):
        """Enable or disable indicator caching.

        Args:
            onoff: If True, enable caching; if False, disable it
        """
        cls._icacheuse = onoff

    @classmethod
    def get_cached_or_create(cls, indicator_cls, *args, **kwargs):
        """Get cached indicator instance or create new one.

        Args:
            indicator_cls: The indicator class to instantiate
            *args: Positional arguments for the indicator
            **kwargs: Keyword arguments for the indicator

        Returns:
            Cached indicator instance if available and caching enabled,
            otherwise a new indicator instance
        """
        if not cls._icacheuse:
            return indicator_cls(*args, **kwargs)

        # Implement a cache to avoid duplicating lines actions
        ckey = (indicator_cls, tuple(args), tuple(kwargs.items()))  # tuples hashable
        try:
            return cls._icache[ckey]
        except TypeError:  # something is not hashable
            return indicator_cls(*args, **kwargs)
        except KeyError:
            pass  # hashable but not in the cache

        _obj = indicator_cls(*args, **kwargs)
        return cls._icache.setdefault(ckey, _obj)


class Indicator(IndicatorBase):
    """Base class for all technical indicators in Backtrader.

    This class provides the foundation for creating custom indicators.
    It manages line data, minimum periods, and calculation logic.
    Indicators inherit from IndicatorBase and integrate with the
    LineIterator system for data flow.

    Attributes:
        _ltype: Line type set to IndType (0) for indicators
        csv: Whether to output this indicator to CSV (default: False)
        aliased: Whether this indicator has an alias name
    """

    _ltype = LineIterator.IndType
    csv = False

    def __getitem__(self, ago):
        """CRITICAL FIX: Forward item access to the first line (e.g., sma line)

        For indicators with named lines like SMA (which has lines.sma), accessing
        indicator[0] should return the value from the first line, not the indicator's
        own array.
        """
        # Use the first line if available
        if hasattr(self, "lines") and hasattr(self.lines, "lines") and len(self.lines.lines) > 0:
            return self.lines.lines[0][ago]
        # Fallback to parent class behavior
        return super().__getitem__(ago)

    # Track if this is an aliased indicator
    aliased = False

    def __init_subclass__(cls, **kwargs):
        """Handle subclass registration and initialization.

        This method is called when a subclass of Indicator is created.
        It performs:
        1. Lines creation using Lines infrastructure
        2. Automatic registration in IndicatorRegistry
        3. Alias handling for module-level access
        4. next/once method setup for calculation modes

        Args:
            **kwargs: Additional keyword arguments
        """
        super().__init_subclass__(**kwargs)

        # CRITICAL FIX: Handle lines creation for indicators like LineSeries does
        # This ensures that lines tuples are converted to Lines instances
        lines = cls.__dict__.get("lines", ())
        extralines = cls.__dict__.get("extralines", 0)

        # Ensure lines is a tuple (it might be a class type)
        if not isinstance(lines, (tuple, list)):
            if hasattr(lines, "_getlines"):
                lines = lines._getlines() or ()
            else:
                lines = ()
        else:
            lines = tuple(lines)  # Ensure it's a tuple

        # Create lines class using the proper Lines infrastructure
        if lines or extralines:
            # Use the LineSeries mechanism to create the lines class
            from .lineseries import Lines

            cls.lines = Lines._derive("lines", lines, extralines, ())
            pass

        # NOTE: __init__ patching for _finalize_minperiod disabled as it's handled elsewhere
        # The minperiod calculation is now done explicitly in indicators that need it (like MACD)
        pass

        # Register subclasses automatically
        if not cls.aliased and cls.__name__ != "Indicator" and not cls.__name__.startswith("_"):
            IndicatorRegistry.register(cls.__name__, cls)

            # Handle aliases - register them to the indicators module
            if hasattr(cls, "alias") and cls.alias:
                import sys

                indicators_module = sys.modules.get("backtrader.indicators")
                if indicators_module:
                    # Set the main class name
                    setattr(indicators_module, cls.__name__, cls)
                    # Set all aliases - handle both tuple and list formats
                    aliases = cls.alias
                    if isinstance(aliases, (list, tuple)):
                        for alias in aliases:
                            if isinstance(alias, str):
                                setattr(indicators_module, alias, cls)

        # Check if next and once have both been overridden
        # Define default methods if they don't exist
        if not hasattr(cls, "next"):
            cls.next = lambda self: None
        if not hasattr(cls, "once"):
            cls.once = lambda self, start, end: None

        next_over = getattr(cls, "next", None) != getattr(Indicator, "next", None)
        once_over = getattr(cls, "once", None) != getattr(Indicator, "once", None)

        # CRITICAL FIX: Also check if once() is the no-op from LineRoot
        # If once is inherited from LineRoot (which is just 'pass'), treat it as not overridden
        # This handles indicators that only set up line bindings without defining next/once
        from .lineroot import LineRoot

        if hasattr(LineRoot, "once") and getattr(cls, "once", None) == getattr(
            LineRoot, "once", None
        ):
            # LineRoot.once is a no-op, so always use once_via_next
            cls.once = cls.once_via_next
            cls.preonce = cls.preonce_via_prenext
            cls.oncestart = cls.oncestart_via_nextstart
        elif next_over and not once_over:
            # No -> need pointer movement to once simulation via next
            cls.once = cls.once_via_next
            cls.preonce = cls.preonce_via_prenext
            cls.oncestart = cls.oncestart_via_nextstart

    # Cache related methods - moved from metaclass
    @classmethod
    def cleancache(cls):
        """Clear the indicator cache"""
        IndicatorRegistry.cleancache()

    @classmethod
    def usecache(cls, onoff):
        """Enable or disable caching"""
        IndicatorRegistry.usecache(onoff)

    def _finalize_minperiod(self):
        """CRITICAL FIX: Finalize minimum period calculation after indicator __init__ completes.

        This method is called after the subclass's __init__ has finished creating
        sub-indicators and line bindings. It ensures that the minimum periods from
        all data sources, lines and sub-indicators are properly propagated to this
        indicator's _minperiod.
        """
        # Step 0: Calculate minperiod from data sources first
        # This is critical for indicators applied to other indicators/lines
        try:
            if hasattr(self, "datas") and self.datas:
                data_minperiods = [getattr(d, "_minperiod", 1) for d in self.datas if d is not None]
                if data_minperiods:
                    data_max = max(data_minperiods)
                    if data_max > self._minperiod:
                        self._minperiod = data_max
        except (AttributeError, TypeError):
            pass

        # Step 1: Calculate minperiod from lines
        try:
            if hasattr(self, "lines") and self.lines is not None:
                line_minperiods = []
                for line in self.lines:
                    mp = getattr(line, "_minperiod", 1)
                    line_minperiods.append(mp)
                if line_minperiods:
                    lines_max = max(line_minperiods)
                    if lines_max > self._minperiod:
                        self._minperiod = lines_max
        except (AttributeError, TypeError):
            pass

        # Step 2: Calculate minperiod from sub-indicators
        try:
            if hasattr(self, "_lineiterators"):
                indicators = self._lineiterators.get(LineIterator.IndType, [])
                if indicators:
                    ind_minperiods = [getattr(ind, "_minperiod", 1) for ind in indicators]
                    if ind_minperiods:
                        ind_max = max(ind_minperiods)
                        if ind_max > self._minperiod:
                            self._minperiod = ind_max
        except (AttributeError, TypeError):
            pass

        # Step 3: Update minperiod on all lines
        try:
            if hasattr(self, "lines") and self.lines is not None:
                for line in self.lines:
                    if hasattr(line, "updateminperiod"):
                        line.updateminperiod(self._minperiod)
        except (AttributeError, TypeError):
            pass

    def advance(self, size=1):
        """Advance indicator lines when data length is less than clock length.

        This method supports indicators with data feeds of different lengths
        (e.g., different timeframes).

        Args:
            size: Number of steps to advance (default: 1)
        """
        # Need intercepting this call to support datas with different lengths (timeframes)
        if len(self) < len(self._clock):
            self.lines.advance(size=size)

    def preonce_via_prenext(self, start, end):
        """Implement preonce using prenext for batch calculation.

        This is a generic implementation if prenext is overridden but preonce is not.
        It loops through the range and calls prenext for each step.

        Args:
            start: Starting index
            end: Ending index
        """
        # Generic implementation if prenext is overridden but preonce is not
        for i in range(start, end):
            # Advance all data feeds
            for data in self.datas:
                data.advance()
            # Advance all sub-indicators
            for indicator in self._lineiterators[LineIterator.IndType]:
                indicator.advance()
            # Advance self
            self.advance()
            # Call prenext
            self.prenext()

    def oncestart_via_nextstart(self, start, end):
        """Implement oncestart using nextstart for batch calculation.

        This is used when nextstart is overridden but oncestart is not.

        Args:
            start: Starting index
            end: Ending index
        """
        # nextstart has been overridden, but oncestart has not - call the overridden nextstart
        for i in range(start, end):
            for data in self.datas:
                data.advance()

            for indicator in self._lineiterators[LineIterator.IndType]:
                indicator.advance()

            self.advance()
            self.nextstart()

    def once_via_next(self, start, end):
        """Implement once using next for batch calculation.

        This is used when next is overridden but once is not.
        It loops through the range and calls next for each step.

        Args:
            start: Starting index
            end: Ending index
        """
        # Not overridden, next must be there ...
        # Simple implementation matching master branch - just advance and call next
        for i in range(start, end):
            for data in self.datas:
                data.advance()

            for indicator in self._lineiterators[LineIterator.IndType]:
                indicator.advance()

            self.advance()
            self.next()


class LinePlotterIndicatorBase(Indicator.__class__):
    """Base class for indicators that plot multiple lines.

    Note: These classes are not currently used in the project.
    They are kept for compatibility with the original backtrader.
    """

    def donew(cls, *args, **kwargs):
        """Create a new LinePlotterIndicator instance.

        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments, must include 'name'

        Returns:
            tuple: (created_object, args, kwargs)
        """
        # Get line name
        lname = kwargs.pop("name")
        # Get class name
        name = cls.__name__
        # Get cls lines, or return Lines if not present
        lines = getattr(cls, "lines", Lines)
        # Derive lines with the new line
        cls.lines = lines._derive(name, (lname,), 0, [])
        # Derive plotlines
        plotlines = AutoInfoClass
        newplotlines = dict()
        newplotlines.setdefault(lname, dict())
        cls.plotlines = plotlines._derive(name, newplotlines, [], recurse=True)

        # Create the object and set the params in place
        _obj, args, kwargs = super().donew(*args, **kwargs)
        # Set _obj owner attribute
        _obj.owner = _obj.data.owner._clock
        # Add another linebuffer
        _obj.data.lines[0].addbinding(_obj.lines[0])
        # Return the object and arguments to the chain
        return _obj, args, kwargs


class LinePlotterIndicator(Indicator, LinePlotterIndicatorBase):
    """Indicator that plots multiple lines.

    Note: This class is not currently used in the project.
    """

    pass
