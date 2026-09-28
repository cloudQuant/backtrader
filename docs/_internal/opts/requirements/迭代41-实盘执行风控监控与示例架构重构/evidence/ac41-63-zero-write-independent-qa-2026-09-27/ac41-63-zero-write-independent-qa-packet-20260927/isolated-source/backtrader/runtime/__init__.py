"""Compatibility facade for :mod:`backtrader_runtime`.

New launchers must import :mod:`backtrader_runtime` directly so strict
configuration rejection happens without initializing the legacy package.
"""

from backtrader_runtime import *  # noqa: F401,F403
