"""Thin, lazy adapter to the public fincore frame-research API.

All labels, transforms, weighting, statistics and report construction belong to
fincore.  This module performs dependency/capability checks, configuration
normalization and typed exception translation only.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import sys
from collections.abc import Mapping
from typing import Any, Dict

from ..errors import (
    ResearchConfigError,
    DataQualityError,
    DatasetError,
    DependencyError,
    FactorComputationError,
)

_RESEARCH_MODULE = "fincore.factor_analysis.research"
_REQUIRED_CAPABILITIES = {
    "api_version": "1.0",
    "result_schema_version": 1,
    "evaluation_config_schema_version": 1,
    "python_min": "3.11",
    "entrypoint": "fincore.factor_analysis.research.evaluate_factor_research",
    "spec": "fincore.factor_analysis.research.ResearchEvaluationSpec",
    "normalizer": "fincore.factor_analysis.research.normalize_research_evaluation_spec",
}
_REQUIRED_TABLES = (
    "signals",
    "labels",
    "ic",
    "ic_summary",
    "quantile_returns",
    "turnover",
    "spreads",
    "stability",
    "correlation",
    "comparisons",
    "coverage",
    "diagnostics",
)
_REQUIRED_METRICS = (
    "pearson_ic",
    "spearman_ic",
    "icir",
    "quantile_returns",
    "spread",
    "rank_autocorrelation",
    "quantile_turnover",
    "factor_correlation",
    "paired_comparison",
)


def _require_python() -> None:
    if sys.version_info < (3, 11):
        raise DependencyError(
            "fincore factor research requires Python 3.11 or newer",
            code="DEPENDENCY_UNAVAILABLE",
        )


def _import_research_module() -> Any:
    _require_python()
    try:
        module = importlib.import_module(_RESEARCH_MODULE)
    except ImportError as exc:
        raise DependencyError(
            "install the committed fincore development build with factor-research support",
            code="DEPENDENCY_UNAVAILABLE",
        ) from exc
    required = (
        "ResearchEvaluationSpec",
        "normalize_research_evaluation_spec",
        "research_capabilities",
        "evaluate_factor_research",
        "ConfigError",
        "DatasetError",
        "DependencyError",
        "DataQualityError",
        "FactorComputationError",
    )
    missing = tuple(name for name in required if not callable(getattr(module, name, None)))
    if missing:
        raise DependencyError(
            "installed fincore factor-research API is incomplete: %s" % ", ".join(missing),
            code="DEPENDENCY_UNAVAILABLE",
        )
    return module


def _check_capabilities(module: Any) -> Mapping:
    capabilities = module.research_capabilities()
    if not isinstance(capabilities, Mapping):
        raise DependencyError(
            "fincore research capabilities must be a mapping",
            code="DEPENDENCY_UNAVAILABLE",
        )
    for key, required_value in _REQUIRED_CAPABILITIES.items():
        if capabilities.get(key) != required_value:
            raise DependencyError(
                "fincore research capability %s is incompatible" % key,
                code="DEPENDENCY_UNAVAILABLE",
            )
    for key, expected in (
        ("labels", {"close_to_close", "next_open_to_open"}),
        ("preprocess", {"cross_section_rank", "cross_section_zscore"}),
        ("metrics", set(_REQUIRED_METRICS)),
        ("result_tables", set(_REQUIRED_TABLES)),
        ("export_formats", {"json", "csv"}),
    ):
        value = capabilities.get(key)
        if not isinstance(value, (tuple, list, set, frozenset)) or not expected.issubset(
            set(value)
        ):
            raise DependencyError(
                "fincore research capabilities do not support %s" % key,
                code="DEPENDENCY_UNAVAILABLE",
            )
    try:
        parameters = inspect.signature(module.evaluate_factor_research).parameters
    except (TypeError, ValueError) as exc:
        raise DependencyError(
            "fincore research entrypoint has no inspectable public signature",
            code="DEPENDENCY_UNAVAILABLE",
        ) from exc
    required_parameters = {
        "factors",
        "grid",
        "prices",
        "universe",
        "groups",
        "precomputed_returns",
        "spec",
    }
    if not required_parameters.issubset(parameters):
        raise DependencyError(
            "fincore research entrypoint signature is incompatible",
            code="DEPENDENCY_UNAVAILABLE",
        )
    if any(
        parameters[name].kind is inspect.Parameter.POSITIONAL_ONLY for name in required_parameters
    ):
        raise DependencyError(
            "fincore research entrypoint does not expose the required keyword API",
            code="DEPENDENCY_UNAVAILABLE",
        )
    return capabilities


def _spec_mapping(spec: Any) -> Dict[str, Any]:
    if spec is None:
        return {}
    if isinstance(spec, Mapping):
        return dict(spec)
    if dataclasses.is_dataclass(spec) and not isinstance(spec, type):
        return {field.name: getattr(spec, field.name) for field in dataclasses.fields(spec)}
    raise ResearchConfigError(
        "evaluation spec must be a mapping or immutable public spec",
        code="INVALID_CONFIG",
    )


def _panel_defaults(panel: Any) -> Dict[str, Any]:
    return {
        "targets": tuple(panel.target_order),
        "start": panel.start,
        "end": panel.end,
    }


def _normalized_spec(module: Any, panel: Any, spec: Any) -> Any:
    values = _panel_defaults(panel)
    values.update(_spec_mapping(spec))
    explicit = values.get("direction_overrides") or {}
    if not isinstance(explicit, Mapping):
        raise ResearchConfigError("direction_overrides must be a mapping", code="INVALID_CONFIG")
    # FactorPanel.directions is the default applied by the adapter;
    # direction_overrides only carries explicit caller overrides.
    values["direction_overrides"] = dict(explicit)
    try:
        return module.normalize_research_evaluation_spec(values)
    except module.ConfigError as exc:
        raise ResearchConfigError(
            str(exc),
            code=getattr(exc, "code", "INVALID_CONFIG"),
            report=getattr(exc, "report", None),
        ) from exc


def _canonicalize_evaluation_index(value: Any, pandas: Any) -> Any:
    """Drop derivable ``freq`` caches so identical timestamps fingerprint equal."""
    if not isinstance(value, (pandas.DataFrame, pandas.Series)):
        return value
    index = value.index
    if isinstance(index, pandas.MultiIndex):
        index = index.remove_unused_levels()
        levels = []
        changed = False
        for level in index.levels:
            if isinstance(level, pandas.DatetimeIndex) and level.freq is not None:
                levels.append(pandas.DatetimeIndex(level, name=level.name, freq=None))
                changed = True
            else:
                levels.append(level)
        if changed:
            index = pandas.MultiIndex(
                levels=levels,
                codes=[code.copy() for code in index.codes],
                sortorder=index.sortorder,
                names=index.names,
                verify_integrity=False,
            )
        value.index = index
    elif isinstance(index, pandas.DatetimeIndex) and index.freq is not None:
        value.index = pandas.DatetimeIndex(index, name=index.name, freq=None)
    return value


def _translate_known_error(module: Any, exc: BaseException) -> BaseException:
    """Translate only declared fincore error classes; never classify by text."""
    classes = getattr(module, "__dict__", {})
    config_cls = classes.get("ConfigError")
    dataset_cls = classes.get("DatasetError")
    dependency_cls = classes.get("DependencyError")
    quality_cls = classes.get("DataQualityError")
    computation_cls = classes.get("FactorComputationError")
    if config_cls is not None and isinstance(exc, config_cls):
        return ResearchConfigError(
            str(exc),
            code=getattr(exc, "code", "INVALID_CONFIG"),
            report=getattr(exc, "report", None),
        )
    if dependency_cls is not None and isinstance(exc, dependency_cls):
        return DependencyError(
            str(exc),
            code=getattr(exc, "code", "DEPENDENCY_UNAVAILABLE"),
            report=getattr(exc, "report", None),
        )
    if quality_cls is not None and isinstance(exc, quality_cls):
        return DataQualityError(
            str(exc),
            code=getattr(exc, "code", "LOSS_LIMIT_EXCEEDED"),
            report=getattr(exc, "report", None),
        )
    if dataset_cls is not None and isinstance(exc, dataset_cls):
        return DatasetError(
            str(exc),
            code=getattr(exc, "code", "INVALID_DATASET"),
            report=getattr(exc, "report", None),
        )
    if computation_cls is not None and isinstance(exc, computation_cls):
        return FactorComputationError(
            str(exc),
            factor=getattr(exc, "factor", "fincore"),
            asset=getattr(exc, "asset", None),
            phase=getattr(exc, "phase", "evaluation"),
            code=getattr(exc, "code", "FACTOR_COMPUTATION_FAILED"),
            report=getattr(exc, "report", None),
        )
    return exc


def evaluate_frames(panel: Any, spec: Any = None) -> Any:
    """Evaluate one :class:`FactorPanel` through fincore's public entry."""
    module = _import_research_module()
    capabilities = _check_capabilities(module)
    normalized = _normalized_spec(module, panel, spec)
    label = getattr(normalized, "label", None)
    if label not in set(capabilities.get("labels", ())):
        raise DependencyError(
            "the installed fincore build does not support label %r" % label,
            code="DEPENDENCY_UNAVAILABLE",
        )
    try:
        pandas = importlib.import_module("pandas")
    except ImportError as exc:
        raise DependencyError(
            "pandas is required to inspect fincore research results",
            code="DEPENDENCY_UNAVAILABLE",
        ) from exc

    factors = _canonicalize_evaluation_index(panel.factors, pandas)
    factors.attrs["factor_directions"] = dict(panel.directions)
    prices = {
        "open": _canonicalize_evaluation_index(panel.prices_open, pandas),
        "close": _canonicalize_evaluation_index(panel.prices_close, pandas),
    }
    try:
        result = module.evaluate_factor_research(
            factors,
            grid=_canonicalize_evaluation_index(panel.grid, pandas),
            prices=prices,
            universe=_canonicalize_evaluation_index(panel.universe, pandas),
            groups=dict(panel.groups),
            precomputed_returns=None,
            spec=normalized,
        )
    except BaseException as exc:
        translated = _translate_known_error(module, exc)
        if translated is exc:
            raise
        raise translated from exc
    required_result = (
        "manifest",
        "signals",
        "labels",
        "ic",
        "ic_summary",
        "quantile_returns",
        "spreads",
        "stability",
        "correlation",
        "comparisons",
        "coverage",
        "diagnostics",
        "status",
        "to_serializable",
        "export",
    )
    missing = tuple(name for name in required_result if not hasattr(result, name))
    if missing:
        raise DependencyError(
            "fincore result does not match its declared schema: %s" % ", ".join(missing),
            code="DEPENDENCY_UNAVAILABLE",
        )
    if not isinstance(result.manifest, Mapping) or result.status not in (
        "OK",
        "PARTIAL",
        "UNEVALUABLE",
    ):
        raise DependencyError(
            "fincore result manifest or status is invalid",
            code="DEPENDENCY_UNAVAILABLE",
        )
    invalid_tables = tuple(
        name
        for name in _REQUIRED_TABLES
        if not isinstance(getattr(result, name, None), pandas.DataFrame)
    )
    if invalid_tables:
        raise DependencyError(
            "fincore result tables do not match their declared schema: %s"
            % ", ".join(invalid_tables),
            code="DEPENDENCY_UNAVAILABLE",
        )
    if not callable(result.to_serializable) or not callable(result.export):
        raise DependencyError(
            "fincore result serialization API is incomplete",
            code="DEPENDENCY_UNAVAILABLE",
        )
    return result


__all__ = ("evaluate_frames",)
