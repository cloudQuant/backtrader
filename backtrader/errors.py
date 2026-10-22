#!/usr/bin/env python
"""Exception Classes Module - Custom exceptions for backtrader.

This module defines the exception hierarchy used throughout the
backtrader framework.

Classes:
    BacktraderError: Base exception for all backtrader exceptions.
    StrategySkipError: Raised to skip a strategy during optimization.
    ModuleImportError: Raised when a required module cannot be imported.
    FromModuleImportError: Raised when a from-style import fails.
    DataError: Raised for data-feed/parsing problems.
    BrokerError: Raised for broker/execution problems.
    OrderError: Raised for order-related problems (subclass of BrokerError).
    ConfigError: Raised for invalid configuration/parameters.
    ResearchError: Base class for typed native-research failures.
    ResearchConfigError: Raised for invalid research configuration.
    DatasetError: Raised for invalid or unsupported research input data.
    DependencyError: Raised when a research dependency is unavailable.
    DataQualityError: Raised when a research quality bound is exceeded.
    FactorComputationError: Raised for unexpected native factor failures.
    FactorComputationContext: Attributes strict failures to their factor context.

Example:
    Raising StrategySkipError during optimization:
    >>> class MyStrategy(bt.Strategy):
    ...     params = (('period', 20),)
    ...
    ...     def __init__(self):
    ...         if self.p.period < 5:
    ...             raise bt.errors.StrategySkipError()
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Dict, Optional, Tuple

# 'from errors import *' exports the base and the most commonly raised classes.
# The category classes are additive (new parents only); existing classes and
# their inheritance are unchanged so isinstance() checks stay compatible.
__all__ = [
    "BacktraderError",
    "StrategySkipError",
    "DataError",
    "BrokerError",
    "OrderError",
    "ConfigError",
    "FACTOR_COMPUTATION_FAILED",
    "ResearchError",
    "ResearchConfigError",
    "DatasetError",
    "DependencyError",
    "DataQualityError",
    "FactorComputationError",
    "FactorComputationContext",
]


# BacktraderError class
class BacktraderError(Exception):
    """Base exception for all backtrader exceptions."""


# StrategySkipError, only this class is used in cerebro
class StrategySkipError(BacktraderError):
    """Requests the platform to skip this strategy for backtesting. To be
    raised during the initialization (``__init__``) phase of the instance"""


# ModuleImportError class
class ModuleImportError(BacktraderError):
    """Raised if a class requests a module to be present to work and it cannot
    be imported"""

    def __init__(self, message, *args):
        """Initialize the ModuleImportError.

        Args:
            message: Error message.
            *args: Additional arguments.
        """
        super().__init__(message, *args)


# FromModuleImportError class
class FromModuleImportError(ModuleImportError):
    """Raised if a class requests a module to be present to work and it cannot
    be imported"""

    def __init__(self, message, *args):
        """Initialize the FromModuleImportError.

        Args:
            message: Error message.
            *args: Additional arguments.
        """
        super().__init__(message, *args)


# ---------------------------------------------------------------------------
# Business exception categories (additive, Sprint 3).
#
# These give callers a meaningful hierarchy to catch
# (e.g. ``except bt.errors.DataError``) without having to enumerate stdlib
# exceptions. They all derive from BacktraderError, so existing
# ``except BacktraderError`` handlers keep working. Nothing here changes the
# parent of a previously existing class, so isinstance() behavior is
# backward compatible.
# ---------------------------------------------------------------------------


class DataError(BacktraderError):
    """Raised for data-feed problems: loading, parsing, or alignment failures."""


class BrokerError(BacktraderError):
    """Raised for broker/execution problems: cash, margin, or matching failures."""


class OrderError(BrokerError):
    """Raised for order-related problems: invalid size/price or rejected orders."""


class ConfigError(BacktraderError):
    """Raised for invalid configuration or parameter values."""


# Native factor-research errors live here so importing the shared exception
# module never depends on the research package or its optional data stack.
FACTOR_COMPUTATION_FAILED = "FACTOR_COMPUTATION_FAILED"


def _freeze_report(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_report(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_report(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_report(item) for item in value)
    return value


class ResearchError(BacktraderError):
    """Base class for stable, machine-readable research failures."""

    default_code = "RESEARCH_ERROR"

    def __init__(
        self,
        message: str = "",
        *,
        code: Optional[str] = None,
        report: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message or code or self.default_code)
        self.code = code or self.default_code
        self.report = _freeze_report(report or {})


class ResearchConfigError(ResearchError, ValueError):
    """Invalid or unsupported research configuration."""

    default_code = "INVALID_CONFIG"


class DatasetError(ResearchError, ValueError):
    """Invalid, incomplete, or unsupported research input data."""

    default_code = "INVALID_DATASET"


class DependencyError(ResearchError, ImportError):
    """A required runtime or public dependency is unavailable."""

    default_code = "DEPENDENCY_UNAVAILABLE"


class DataQualityError(ResearchError, ValueError):
    """A requested quality bound is exceeded by the collected dataset."""

    default_code = "LOSS_LIMIT_EXCEEDED"


class FactorComputationError(ResearchError, RuntimeError):
    """An unexpected native factor or line calculation failure.

    ``__cause__`` is kept by normal Python exception chaining. Callers should
    raise the result of :meth:`FactorComputationContext.wrap` with ``from`` the
    original exception so its type and traceback remain available.
    """

    default_code = FACTOR_COMPUTATION_FAILED

    def __init__(
        self,
        message: str = "factor computation failed",
        *,
        factor: str,
        asset: Optional[str],
        phase: str,
        code: str = FACTOR_COMPUTATION_FAILED,
        report: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if not isinstance(factor, str) or not factor:
            raise TypeError("factor must be a non-empty string")
        if asset is not None and (not isinstance(asset, str) or not asset):
            raise TypeError("asset must be None or a non-empty string")
        if not isinstance(phase, str) or not phase:
            raise TypeError("phase must be a non-empty string")
        super().__init__(message, code=code, report=report)
        self.factor = factor
        self.asset = asset
        self.phase = phase


class FactorComputationContext:
    """Duck-typed strict policy context propagated through one native factor.

    The core only needs the public ``phase``, ``asset_for`` and ``wrap``
    protocol. Feed and output-line references are retained by identity so an
    error is attributed only when one asset can be identified unambiguously.
    """

    __slots__ = ("factor", "phase", "failed", "error", "_asset_by_object_id")

    def __init__(
        self,
        factor: str,
        assets_by_object: Optional[Mapping[Any, str]] = None,
        *,
        phase: str = "construct",
    ) -> None:
        if not isinstance(factor, str) or not factor:
            raise TypeError("factor must be a non-empty string")
        if not isinstance(phase, str) or not phase:
            raise TypeError("phase must be a non-empty string")
        self.factor = factor
        self.phase = phase
        self.failed = False
        self.error = None
        self._asset_by_object_id: Dict[int, str] = {}
        for obj, asset in (assets_by_object or {}).items():
            self.bind_object(obj, asset)

    def bind_object(self, obj: Any, asset: str) -> None:
        """Bind a feed or concrete output line to its declared asset name."""
        if obj is None:
            raise TypeError("cannot bind a missing object to an asset")
        if not isinstance(asset, str) or not asset:
            raise TypeError("asset must be a non-empty string")
        self._asset_by_object_id[id(obj)] = asset

    def asset_for(self, operation: Any = None) -> Optional[str]:
        """Resolve an asset from an operation or its direct data operands.

        Cross-sectional operations touching multiple assets intentionally
        return ``None``; callers must not guess one member of the panel.
        """
        if operation is None:
            return None

        found = set()
        seen = set()
        pending: Tuple[Any, ...] = (operation,)
        depth = 0
        while pending and depth < 32:
            current = pending[0]
            pending = pending[1:]
            depth += 1
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            asset = self._asset_by_object_id.get(identity)
            if asset is not None:
                found.add(asset)
                continue

            children = []
            for name in ("data", "data0", "data1", "owner", "_owner"):
                candidate = getattr(current, name, None)
                if candidate is not None and candidate is not current:
                    children.append(candidate)
            for name in ("datas", "_datas", "inputs", "_inputs"):
                candidates = getattr(current, name, None)
                if isinstance(candidates, (tuple, list)):
                    children.extend(candidates)
            pending += tuple(children)

        if len(found) == 1:
            return next(iter(found))
        return None

    def wrap(
        self,
        exc: BaseException,
        *,
        phase: Optional[str] = None,
        asset: Optional[str] = None,
    ) -> FactorComputationError:
        """Build a safe structured error; preserve ``exc`` via ``raise from``."""
        if isinstance(exc, FactorComputationError):
            return exc
        selected_phase = phase or self.phase or "unknown"
        selected_asset = asset if asset is not None else self.asset_for(exc)
        report = {"exception_type": type(exc).__name__}
        return FactorComputationError(
            "factor computation failed",
            factor=self.factor,
            asset=selected_asset,
            phase=selected_phase,
            report=report,
        )
