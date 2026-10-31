"""Compatibility imports for :mod:`backtrader_runtime.config`."""

import backtrader_runtime.config as _implementation

__all__ = [name for name in vars(_implementation) if not name.startswith("_")]
globals().update({name: getattr(_implementation, name) for name in __all__})
