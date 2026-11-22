#!/usr/bin/env python
"""AutoDict Module - Enhanced dictionary classes.

This module provides dictionary subclasses with automatic key creation,
dot notation access, and ordered dict support.

Classes:
    AutoDict: Dict with automatic nested dict creation.
    AutoOrderedDict: OrderedDict with automatic nested dict creation.
    DotDict: Dict with attribute-style access (obj.key).
    AutoDictList: Dict with automatic list creation for missing keys.

Example:
    >>> d = AutoOrderedDict()
    >>> d['a']['b']['c'] = 1  # Automatically creates nested dicts
    >>> print(d['a']['b']['c'])
    1
"""

import operator
from collections import OrderedDict, defaultdict

from ..utils.log_message import get_logger
from .py3 import values as py3lvalues

logger = get_logger(__name__)


def Tree():
    """Create a recursive defaultdict structure.

    Returns a defaultdict that automatically creates nested defaultdicts
    for any missing key, allowing for infinite nesting.

    Returns:
        defaultdict: A recursive defaultdict structure.
    """
    return defaultdict(Tree)


class AutoDictList(dict):
    """Dictionary that creates an empty list for missing keys.

    When accessing a key that doesn't exist, automatically creates
    a new empty list for that key.

    Example:
        >>> d = AutoDictList()
        >>> d['key'].append('value')
        >>> print(d['key'])
        ['value']
    """

    # Inherits dict, when accessing missing key, will automatically generate a key value, corresponding value is an empty list
    # This newly created class is only used in collections.defaultdict(AutoDictList) line
    def __missing__(self, key):
        value = self[key] = []
        return value


class DotDict(dict):
    """Dictionary with attribute-style access.

    Allows accessing dictionary values as attributes using dot notation.
    If an attribute is not found in the usual places, the dict itself
    is checked.

    Example:
        >>> d = DotDict()
        >>> d['key'] = 'value'
        >>> print(d.key)
        'value'
    """

    # If the attribute is not found in the usual places, try the dict itself
    # This class is only used in the following line, when accessing attributes, if attribute doesn't exist, __getattr__ will be called
    # _obj.dnames = DotDict([(d._name, d) for d in _obj.datas if getattr(d, '_name', '')])
    def __getattr__(self, key):
        if key.startswith("__"):
            # return super().__getattr__(key)
            raise AttributeError(key)
        return self[key]


# This function has slightly wider usage, mainly called in tradeanalyzer and ibstore, is an extension of Python dict
# Compared to Python built-in dict, added an attribute: _closed, added functions _close, _open, __missing__, __getattr__, overrode __setattr__
class AutoDict(dict):
    """Dictionary with automatic nested dict creation and closeable state.

    Extends dict with:
    - Automatic nested dict creation for missing keys
    - Closeable state (_closed) to prevent further auto-creation
    - Attribute-style access

    Attributes:
        _closed: If True, __missing__ raises KeyError instead of creating nested dicts.

    Methods:
        _close(): Set _closed to True to prevent auto-creation.
        _open(): Set _closed to False to enable auto-creation.
    """

    # Initialize default attribute _closed to False
    _closed = False

    # _close method
    def _close(self):
        # Change class attribute to True
        self._closed = True
        # For values in dict, if they are instances of AutoDict or AutoOrderedDict, call _close method to set attribute _closed to True
        for key, val in self.items():
            if isinstance(val, (AutoDict, AutoOrderedDict)):
                val._close()

    # _open method, set _closed attribute to False
    def _open(self):
        self._closed = False
        for key, val in self.items():
            if isinstance(val, (AutoDict, AutoOrderedDict)):
                val._open()

    # __missing__ method handles case when key doesn't exist, if _closed, return KeyError, if not, create an AutoDict() instance for this key
    def __missing__(self, key):
        if self._closed:
            raise KeyError(key)

        value = self[key] = AutoDict()
        return value

    def __getattr__(self, key):
        if key.startswith("_"):
            raise AttributeError(key)
        try:
            return self[key]
        except KeyError:
            logger.debug("autodict: key not found, re-raising KeyError")
            raise AttributeError(key) from None

    def __setattr__(self, key, value):
        if key.startswith("_"):
            self.__dict__[key] = value
            return
        self[key] = value


# Created a new ordered dict, added some functions, similar to AutoDict
class AutoOrderedDict(OrderedDict):
    """OrderedDict with automatic nested dict creation and closeable state.

    Combines OrderedDict's insertion ordering with AutoDict's automatic
    nested dict creation and closeable state.

    Attributes:
        _closed: If True, __missing__ raises KeyError instead of creating nested dicts.

    Methods:
        _close(): Set _closed to True to prevent auto-creation.
        _open(): Set _closed to False to enable auto-creation.

    Example:
        >>> d = AutoOrderedDict()
        >>> d['a']['b'] = 1  # Automatically creates nested dicts
        >>> d._close()  # Prevent further auto-creation
    """

    _closed = False

    def _close(self):
        self._closed = True
        for key, val in self.items():
            if isinstance(val, (AutoDict, AutoOrderedDict)):
                val._close()

    def _open(self):
        self._closed = False
        for key, val in self.items():
            if isinstance(val, (AutoDict, AutoOrderedDict)):
                val._open()

    def __missing__(self, key):
        if self._closed:
            raise KeyError(key)

        # value = self[key] = type(self)()
        value = self[key] = AutoOrderedDict()
        return value

    # __getattr__ and __setattr__ functions are much more normal compared to AutoDict
    def __getattr__(self, key):
        if key.startswith("_"):
            raise AttributeError(key)
        try:
            return self[key]
        except KeyError:
            logger.debug("autodict: attribute miss, re-raising KeyError")
            raise AttributeError(key) from None

    def __setattr__(self, key, value):
        if key.startswith("_"):
            self.__dict__[key] = value
            return

        self[key] = value

    def _binary_op(self, other, op):
        """Apply a key-wise binary arithmetic operation with another AutoOrderedDict.

        Keys are combined in insertion order (``self`` keys first, then any
        additional keys from ``other``).  Nested ``AutoOrderedDict`` values are
        combined recursively.  When a key exists in only one operand, the
        missing side uses a zero/default instance of the present value's type
        (an empty ``AutoOrderedDict`` for nested dicts, or ``type(val)()`` for
        scalar values), matching the auto-initialization contract of in-place
        operations.

        Returns ``NotImplemented`` if ``other`` is not an ``AutoOrderedDict``.
        """
        if not isinstance(other, AutoOrderedDict):
            return NotImplemented

        result = AutoOrderedDict()
        for key in self:
            if key in other:
                result[key] = op(self[key], other[key])
            else:
                val = self[key]
                zero = AutoOrderedDict() if isinstance(val, AutoOrderedDict) else type(val)()
                result[key] = op(val, zero)

        for key in other:
            if key not in self:
                val = other[key]
                zero = AutoOrderedDict() if isinstance(val, AutoOrderedDict) else type(val)()
                result[key] = op(zero, val)

        return result

    def _inplace_op(self, other, op):
        """Apply an in-place arithmetic operation on this AutoOrderedDict.

        - If ``other`` is an ``AutoOrderedDict``: compute the key-wise result
          first (so errors leave ``self`` unmodified), then update ``self`` in
          place and return ``self``.
        - If ``self`` is empty (the auto-created placeholder produced by
          ``__missing__``) and ``other`` supports ``type(other)()`` arithmetic:
          return ``op(type(other)(), other)`` so patterns such as
          ``d.total.open += 1`` initialize leaf counters.
        - Otherwise return ``NotImplemented`` so Python raises ``TypeError``.
        """
        if isinstance(other, AutoOrderedDict):
            combined = self._binary_op(other, op)
            self.clear()
            self.update(combined)
            return self

        if self:
            return NotImplemented

        try:
            zero = type(other)()
        except TypeError:
            return NotImplemented

        try:
            return op(zero, other)
        except TypeError:
            return NotImplemented

    def __add__(self, other):
        """Return a new AutoOrderedDict with key-wise sums."""
        return self._binary_op(other, operator.add)

    def __sub__(self, other):
        """Return a new AutoOrderedDict with key-wise differences."""
        return self._binary_op(other, operator.sub)

    def __mul__(self, other):
        """Return a new AutoOrderedDict with key-wise products."""
        return self._binary_op(other, operator.mul)

    def __truediv__(self, other):
        """Return a new AutoOrderedDict with key-wise quotients."""
        return self._binary_op(other, operator.truediv)

    def __iadd__(self, other):
        """In-place key-wise addition or empty-placeholder scalar initialization."""
        return self._inplace_op(other, operator.add)

    def __isub__(self, other):
        """In-place key-wise subtraction or empty-placeholder scalar initialization."""
        return self._inplace_op(other, operator.sub)

    def __imul__(self, other):
        """In-place key-wise multiplication or empty-placeholder scalar initialization."""
        return self._inplace_op(other, operator.mul)

    def __itruediv__(self, other):
        """In-place key-wise true division or empty-placeholder scalar initialization."""
        return self._inplace_op(other, operator.truediv)

    def lvalues(self):
        """Return dictionary values as a list.

        Provides Python 2/3 compatible list of values.

        Returns:
            list: List of all values in the dictionary.
        """
        return py3lvalues(self)


if __name__ == "__main__":
    aod = AutoOrderedDict()
    print("aod", dir(aod))
    od: dict = OrderedDict()
    print("od", dir(od))
