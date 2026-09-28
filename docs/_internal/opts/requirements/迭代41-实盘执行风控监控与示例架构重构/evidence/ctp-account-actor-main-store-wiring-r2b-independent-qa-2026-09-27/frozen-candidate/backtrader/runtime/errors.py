"""Compatibility imports for :mod:`backtrader_runtime.errors`.

Use the top-level :mod:`backtrader_runtime` package for configuration-first
entry points. Importing a ``backtrader.*`` child necessarily initializes the
legacy Backtrader package before this facade can run.
"""

from backtrader_runtime.errors import *  # noqa: F401,F403
