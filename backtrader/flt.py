#!/usr/bin/env python
"""Filter Module - Data filtering for backtrader.

This module provides the base Filter class for data filtering operations.
Filters can be applied to data feeds to modify or filter bars during
backtesting.

Classes:
    Filter: Base class for data filters.

Example:
    >>> class MyFilter(bt.Filter):
    ...     def next(self, data):
    ...         # Modify data bar
    ...         pass
"""

from .parameters import ParameterizedBase

__all__ = ["Filter"]


# Filter class - refactored to use new parameter system
class Filter(ParameterizedBase):
    """Base class for data filters in backtrader.

    Filters process data bars and can modify or reject them. Subclasses
    should override the next() method to implement custom filtering logic.

    Attributes:
        _firsttime: Tracks if this is the first call.

    This class has been refactored from MetaParams to the new ParameterizedBase
    system for Day 36-38 of the metaprogramming removal project.
    """

    _firsttime = True

    def __init__(self, data_, **kwargs):
        """Initialize the Filter.

        Args:
            data_: The data feed to filter.
            **kwargs: Additional keyword arguments for parameters.
        """
        # Call parent class initialization
        super().__init__(**kwargs)

    def __call__(self, data):
        """Process a data bar through the filter.

        Args:
            data: The data feed being filtered.
        """
        # If first time, call nextstart, then set _firsttime to False
        if self._firsttime:
            self.nextstart(data)
            self._firsttime = False
        # Call next
        self.next(data)

    def nextstart(self, data):
        """Called on the first bar before filtering starts.

        Args:
            data: The data feed being filtered.

        Note:
            Override this method to perform one-time initialization.
        """
        pass

    def next(self, data):
        """Process each data bar.

        Args:
            data: The data feed being filtered.

        Note:
            Subclasses must override this method to implement filtering logic.
        """
        pass
