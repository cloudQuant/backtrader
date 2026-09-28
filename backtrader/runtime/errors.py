"""Compatibility imports for :mod:`backtrader_runtime.errors`.

Use the top-level :mod:`backtrader_runtime` package for configuration-first
entry points. Importing a ``backtrader.*`` child necessarily initializes the
legacy Backtrader package before this facade can run.
"""

import backtrader_runtime.errors as _implementation

__all__ = [name for name in vars(_implementation) if not name.startswith("_")]
globals().update({name: getattr(_implementation, name) for name in __all__})
