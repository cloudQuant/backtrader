#!/usr/bin/env python
"""Python 3 Compatibility Module.

This module provides common type aliases and utility functions used
throughout the backtrader framework. Originally a Python 2/3 shim,
now simplified to Python 3 only.

Exports:
    string_types: Tuple of string types — ``(str,)``.
    integer_types: Tuple of integer types — ``(int,)``.
    MAXINT / MININT / MAXFLOAT / MINFLOAT: Numeric limits.
    range, zip, map, filter: Built-in references (kept for import compat).
    queue: ``import queue``.
    cmp, bytes, bstr: Helper functions.
    iterkeys, itervalues, iteritems, keys, values, items: Dict helpers.
    urlquote, urlopen, ProxyHandler, build_opener, install_opener: URL helpers.
    winreg: Windows registry module (None on non-Windows).
    with_metaclass: Metaclass helper.
"""

import queue  # noqa: F401 — re-exported
import sys
import urllib.request as _urllib_request
from urllib.parse import quote as _urlquote

# Kept for backward compat — always False
PY2 = False

# --- Windows registry ---
try:
    import winreg  # noqa: F401
except ImportError:
    winreg = None

# --- URL helpers (used by feeds like Quandl, Yahoo) ---
def urlquote(s, *args, **kwargs):
    return _urlquote(s, *args, **kwargs)

def urlopen(*args, **kwargs):
    return _urllib_request.urlopen(*args, **kwargs)

def ProxyHandler(*args, **kwargs):  # noqa: N802 — keep legacy name
    return _urllib_request.ProxyHandler(*args, **kwargs)

def build_opener(*args, **kwargs):
    return _urllib_request.build_opener(*args, **kwargs)

def install_opener(*args, **kwargs):
    return _urllib_request.install_opener(*args, **kwargs)

# --- Numeric limits ---
MAXINT = sys.maxsize
MININT = -sys.maxsize - 1
MAXFLOAT = sys.float_info.max
MINFLOAT = sys.float_info.min

# --- Type aliases ---
string_types = (str,)
integer_types = (int,)
long = int

# --- Built-in re-exports (kept so ``from .py3 import range`` still works) ---
filter = filter
map = map
range = range
zip = zip


# --- Utility functions ---
def cmp(a, b):
    """Compare *a* and *b*, return 1 / 0 / -1."""
    return (a > b) - (a < b)

def bytes(x):
    return x.encode("utf-8")

def bstr(x):
    return str(x)


# --- Dict iteration helpers ---
def iterkeys(d):
    return iter(d.keys())

def itervalues(d):
    return iter(d.values())

def iteritems(d):
    return iter(d.items())

def keys(d):
    return list(d.keys())

def values(d):
    return list(d.values())

def items(d):
    return list(d.items())


# This is from Armin Ronacher from Flash simplified later by six
def with_metaclass(meta, *bases):
    """Create a base class with a metaclass."""

    # This requires a bit of explanation: the basic idea is to make a dummy
    # metaclass for one level of class instantiation that replaces itself with
    # the actual metaclass.
    # This function creates a base class with a metaclass, main purpose is to be compatible with python2 and python3 syntax, now there's a newer solution is to use decorator @six.add_metaclass(Meta)
    # References: https://qa.1r1g.com/sf/ask/1295967501/
    # https://zhuanlan.zhihu.com/p/354828950
    # https://www.jianshu.com/p/224ffcb8e73e
    class metaclass(meta):
        """Dummy metaclass for creating a temporary base class.

        This metaclass is used internally by with_metaclass to create a
        temporary class that will be replaced with the actual metaclass.

        Attributes:
            meta: The target metaclass to use for the final class.
        """

        def __new__(cls, name, this_bases, d):
            """Create a new class with the target metaclass.

            Args:
                cls: The metaclass class (metaclass itself).
                name: Name of the class being created.
                this_bases: Base classes for the temporary class.
                d: Class dictionary.

            Returns:
                A new class created with the target metaclass and specified bases.
            """
            return meta(name, bases, d)

    return type.__new__(metaclass, "temporary_class", (), {})
