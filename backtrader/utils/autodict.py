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
from collections import OrderedDict, defaultdict

# from .py3 import values as py3lvalues
from backtrader.utils.py3 import values as py3lvalues  # Changed relative import to absolute import


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
        value = self[key] = list()
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
            return super().__getattr__(key)
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

    # __missing__ method handles case when key doesn't exist, if _closed, return KeyError, if not, create an AutoDict() instance for this key
    def __missing__(self, key):
        if self._closed:
            raise KeyError

        value = self[key] = AutoDict()
        return value

    # __getattr__ method is redundant, if will never be reached, can delete if statement, even this method can be deleted
    def __getattr__(self, key):
        if False and key.startswith("_"):
            raise AttributeError

        return self[key]

    # __setattr__ method is also redundant, can consider deleting
    def __setattr__(self, key, value):
        if False and key.startswith("_"):
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

    def __missing__(self, key):
        if self._closed:
            raise KeyError

        # value = self[key] = type(self)()
        value = self[key] = AutoOrderedDict()
        return value

    # __getattr__ and __setattr__ functions are much more normal compared to AutoDict
    def __getattr__(self, key):
        if key.startswith("_"):
            raise AttributeError

        return self[key]

    def __setattr__(self, key, value):
        if key.startswith("_"):
            self.__dict__[key] = value
            return

        self[key] = value

    # Defined math operations, not sure what they mean for now, but it seems only __iadd__ and __isub__ are normal
    # Define math operations
    def __iadd__(self, other):
        if not isinstance(other, type(self)):
            return type(other)() + other

        return self + other

    def __isub__(self, other):
        if not isinstance(other, type(self)):
            return type(other)() - other

        return self - other

    def __imul__(self, other):
        if not isinstance(other, type(self)):
            return type(other)() * other

        return self + other

    def __idiv__(self, other):
        if not isinstance(other, type(self)):
            return type(other)() // other

        return self + other

    def __itruediv__(self, other):
        if not isinstance(other, type(self)):
            return type(other)() / other

        return self + other

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
    od = OrderedDict()
    print("od", dir(od))
