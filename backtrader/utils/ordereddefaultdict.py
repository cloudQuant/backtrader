#!/usr/bin/env python
"""Ordered Default Dict Module - OrderedDict with default values.

This module provides OrderedDefaultdict, which combines the insertion
ordering of OrderedDict with the default value functionality of defaultdict.

Classes:
    OrderedDefaultdict: OrderedDict that creates default values for missing keys.

Example:
    >>> from backtrader.utils import OrderedDefaultdict
    >>> d = OrderedDefaultdict(list)
    >>> d['key'].append('value')
    >>> print(d['key'])
    ['value']
"""
from collections import OrderedDict

from .py3 import iteritems


# This is an unused class. The intention of creating it should be to maintain DefaultDict characteristics when adding to OrderedDict
# This class is not found anywhere in backtrader, everyone can ignore it, it can even be deleted without affecting usage.
class OrderedDefaultdict(OrderedDict):
    """OrderedDict that creates default values for missing keys.

    Combines the insertion ordering of OrderedDict with the automatic
    default value creation of defaultdict.

    Attributes:
        default_factory: Callable that creates default values for missing keys.

    Example:
        >>> d = OrderedDefaultdict(list)
        >>> d['items'].append(1)
        >>> print(d['items'])
        [1]
    """

    # Class initialization, passing *args parameters and **kwargs parameters
    def __init__(self, *args, **kwargs):
        """Initialize the OrderedDefaultdict.

        Args:
            *args: If provided, first argument must be a callable that
                creates default values for missing keys (like list, dict, int).
                Remaining args are passed to OrderedDict.
            **kwargs: Keyword arguments passed to OrderedDict.

        Raises:
            TypeError: If first argument is not None or callable.
        """
        # If no *args passed, default self.default_factory is None
        if not args:
            self.default_factory = None
        # If *args passed, if args[0] doesn't satisfy being None or callable, will raise error, if satisfied, default will be args[0], remaining parameters will be args[1:]
        else:
            if not (args[0] is None or callable(args[0])):
                raise TypeError("first argument must be callable or None")
            self.default_factory = args[0]
            args = args[1:]
        super().__init__(*args, **kwargs)

    # When key value doesn't exist, if self.default_factory is None, will return key error; if not None, will return self.default_factory()
    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        self[key] = default = self.default_factory()
        return default

    # Optional method, for supporting pickle
    def __reduce__(self):  # optional, for pickle support
        args = (self.default_factory,) if self.default_factory else ()
        return self.__class__, args, None, None, iteritems(self)
