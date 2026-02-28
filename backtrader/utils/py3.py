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
    """Quote a string for use in a URL.

    Args:
        s: The string to quote.
        *args: Additional positional arguments passed to urllib.parse.quote.
        **kwargs: Additional keyword arguments passed to urllib.parse.quote.

    Returns:
        The quoted string safe for use in URLs.
    """
    return _urlquote(s, *args, **kwargs)


def urlopen(*args, **kwargs):
    """Open a URL.

    Args:
        *args: Positional arguments passed to urllib.request.urlopen.
        **kwargs: Keyword arguments passed to urllib.request.urlopen.

    Returns:
        A file-like object representing the URL response.
    """
    return _urllib_request.urlopen(*args, **kwargs)


def ProxyHandler(*args, **kwargs):  # noqa: N802 — keep legacy name
    """Create a proxy handler for opening URLs.

    Args:
        *args: Positional arguments passed to urllib.request.ProxyHandler.
        **kwargs: Keyword arguments passed to urllib.request.ProxyHandler.

    Returns:
        A ProxyHandler instance for configuring URL proxies.
    """
    return _urllib_request.ProxyHandler(*args, **kwargs)


def build_opener(*args, **kwargs):
    """Build a URL opener with a chain of handlers.

    Args:
        *args: Positional arguments passed to urllib.request.build_opener.
        **kwargs: Keyword arguments passed to urllib.request.build_opener.

    Returns:
        An OpenerDirector instance configured with the specified handlers.
    """
    return _urllib_request.build_opener(*args, **kwargs)


def install_opener(*args, **kwargs):
    """Install an opener as the default global opener.

    Args:
        *args: Positional arguments passed to urllib.request.install_opener.
        **kwargs: Keyword arguments passed to urllib.request.install_opener.

    Returns:
        None.
    """
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
    """Compare two values.

    Args:
        a: First value to compare.
        b: Second value to compare.

    Returns:
        int: 1 if a > b, 0 if a == b, -1 if a < b.
    """
    return (a > b) - (a < b)


def bytes(x):
    """Encode a string to bytes using UTF-8 encoding.

    Args:
        x: String to encode.

    Returns:
        Bytes representation of the input string.
    """
    return x.encode("utf-8")


def bstr(x):
    """Convert a value to a byte string.

    Args:
        x: Value to convert.

    Returns:
        String representation of the input value.
    """
    return str(x)


# --- Dict iteration helpers ---
def iterkeys(d):
    """Return an iterator over the dictionary's keys.

    Args:
        d: Dictionary to iterate over.

    Returns:
        An iterator over the dictionary's keys.
    """
    return iter(d.keys())


def itervalues(d):
    """Return an iterator over the dictionary's values.

    Args:
        d: Dictionary to iterate over.

    Returns:
        An iterator over the dictionary's values.
    """
    return iter(d.values())


def iteritems(d):
    """Return an iterator over the dictionary's items.

    Args:
        d: Dictionary to iterate over.

    Returns:
        An iterator over (key, value) tuples.
    """
    return iter(d.items())


def keys(d):
    """Return a list of the dictionary's keys.

    Args:
        d: Dictionary to extract keys from.

    Returns:
        A list containing the dictionary's keys.
    """
    return list(d.keys())


def values(d):
    """Return a list of the dictionary's values.

    Args:
        d: Dictionary to extract values from.

    Returns:
        A list containing the dictionary's values.
    """
    return list(d.values())


def items(d):
    """Return a list of the dictionary's items.

    Args:
        d: Dictionary to extract items from.

    Returns:
        A list of (key, value) tuples.
    """
    return list(d.items())


# This is from Armin Ronacher from Flash simplified later by six
def with_metaclass(meta, *bases):
    """Create a base class with a metaclass.

    This function provides a compatibility layer for creating classes with
    metaclasses in a way that works across Python versions. Originally designed
    for Python 2/3 compatibility, now simplified for Python 3 only.

    Args:
        meta: The metaclass to use for the created class.
        *bases: Base classes to inherit from.

    Returns:
        A temporary base class that, when inherited from, creates a class
        with the specified metaclass and base classes.

    Note:
        Modern Python 3 code can use metaclass directly in class definition:
        ``class MyClass(metaclass=Meta):``. This function is kept for
        backward compatibility with existing code.
    """

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
