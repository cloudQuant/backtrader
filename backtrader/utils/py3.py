#!/usr/bin/env python
"""Python 2/3 Compatibility Module.

This module provides compatibility shims to support both Python 2 and Python 3.
It defines common types and functions that work across Python versions.

Exports:
    PY2: Boolean indicating if running on Python 2.
    string_types: Tuple of string types.
    integer_types: Tuple of integer types.
    range: Python 3 style range function.
    zip: Python 3 style zip function.
    map: Python 3 style map function.
    filter: Python 3 style filter function.
    MAXINT: Maximum integer value.
"""
import sys

PY2 = (
    sys.version_info.major == 2
)  # Get current Python version, check if it's python2

# If python2
if PY2:
    # # Try to import _winreg module, if callable, it proves this system is Windows, can be used for Windows registry related operations;
    # # If import raises an error, it means the system is not Windows, set winreg to None
    # try:
    #     import _winreg as winreg
    # except ImportError:
    #     winreg = None
    # # Maximum integer allowed by the system
    # MAXINT = sys.maxint
    # # Minimum integer allowed by the system
    # MININT = -sys.maxint - 1
    # # Maximum float allowed by the system
    # MAXFLOAT = sys.float_info.max
    # # Minimum float allowed by the system
    # MINFLOAT = sys.float_info.min
    # # String types
    # string_types = str, unicode
    # # Integer types
    # integer_types = int, long
    # # Filter function
    # filter = itertools.ifilter
    # # Map function
    # map = itertools.imap
    # # Create integer iterator function range
    # range = xrange
    # # Function to pair elements into tuples
    # zip = itertools.izip
    # # Long integer
    # long = long
    # # Comparison function
    # cmp = cmp
    # # Generate bytes
    # bytes = bytes
    # bstr = bytes
    # # String buffer
    # from io import StringIO
    # # Web crawler module
    # from urllib2 import urlopen, ProxyHandler, build_opener, install_opener
    # from urllib import quote as urlquote
    # # Dictionary iteration
    # def iterkeys(d): return d.iterkeys()
    #
    # def itervalues(d): return d.itervalues()
    #
    # def iteritems(d): return d.iteritems()
    # # Dictionary values
    # def keys(d): return d.keys()
    #
    # def values(d): return d.values()
    #
    # def items(d): return d.items()
    #
    # import Queue as queue
    pass


else:
    # python3 comments are similar to the comments above
    try:
        import winreg
    except ImportError:
        winreg = None

    # Python 3 URL helpers, used by some feeds (for example Quandl)
    import urllib.request as _urllib_request
    from urllib.parse import quote as _urlquote

    def urlquote(s, *args, **kwargs):
        return _urlquote(s, *args, **kwargs)

    def urlopen(*args, **kwargs):
        return _urllib_request.urlopen(*args, **kwargs)

    def ProxyHandler(*args, **kwargs):  # noqa: N802 - keep legacy name
        return _urllib_request.ProxyHandler(*args, **kwargs)

    def build_opener(*args, **kwargs):
        return _urllib_request.build_opener(*args, **kwargs)

    def install_opener(*args, **kwargs):
        return _urllib_request.install_opener(*args, **kwargs)

    MAXINT = sys.maxsize
    MININT = -sys.maxsize - 1

    MAXFLOAT = sys.float_info.max
    MINFLOAT = sys.float_info.min

    string_types = (str,)
    integer_types = (int,)

    filter = filter
    map = map
    range = range
    zip = zip
    long = int

    # Note, this cmp is a custom function, return value is 1, 0, -1
    def cmp(a, b):
        return (a > b) - (a < b)

    def bytes(x):
        return x.encode("utf-8")

    def bstr(x):
        return str(x)

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

    import queue as queue


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
        def __new__(cls, name, this_bases, d):
            return meta(name, bases, d)

    return type.__new__(metaclass, "temporary_class", (), {})
