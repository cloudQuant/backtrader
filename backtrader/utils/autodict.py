#!/usr/bin/env python

from collections import OrderedDict, defaultdict

# from .py3 import values as py3lvalues
from backtrader.utils.py3 import values as py3lvalues  # Changed relative import to absolute import


def Tree():
    # Not sure what this function is for, not used elsewhere, ignore
    # Consider deleting
    return defaultdict(Tree)


class AutoDictList(dict):
    # Inherits dict, when accessing missing key, will automatically generate a key value, corresponding value is an empty list
    # This newly created class is only used in collections.defaultdict(AutoDictList) line
    def __missing__(self, key):
        value = self[key] = list()
        return value


class DotDict(dict):
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
        return py3lvalues(self)


if __name__ == "__main__":
    aod = AutoOrderedDict()
    print("aod", dir(aod))
    od = OrderedDict()
    print("od", dir(od))
