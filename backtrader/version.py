#!/usr/bin/env python
"""Version Module - Backtrader version information.

This module contains version information for the backtrader package.

Attributes:
    __version__: Version string (e.g., "1.9.76.123").
    __btversion__: Version tuple for comparisons (e.g., (1, 9, 76, 123)).

Example:
    Checking version:
    >>> import backtrader
    >>> print(backtrader.__version__)
    1.9.76.123
"""

# backtrader version number
__version__ = "1.0.1"

# backtrader version number, tuple format
__btversion__ = tuple(int(x) for x in __version__.split("."))
