"""Thin, lazy adapter to the public fincore factor-research API.

All formula math, labels, transforms, weighting, statistics, and report
construction belong to fincore. This module performs dependency/capability
checks, configuration normalization, and typed exception translation only.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import sys
from collections.abc import Mapping
from typing import Any, Dict, cast

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
        ("labels", {"close_to_close", "next_open_to_open", "precomputed"}),
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
    if capabilities.get("charts_supported") is not True:
        raise DependencyError(
            "fincore research capability does not support explicit chart export",
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


def _dataset_defaults(dataset: Any) -> Dict[str, Any]:
    metadata = dataset._metadata
    research = metadata.get("research", {})
    return {
        "targets": tuple(dataset._targets),
        "start": dataset._start,
        "end": dataset._end,
        "snapshot_id": research.get("snapshot_id", "unspecified"),
        "price_basis": research.get("price_basis", "unspecified"),
        "calendar_id": research.get("calendar_id", "unspecified"),
        "frequency": research.get("frequency", "unspecified"),
    }


def _factor_directions(dataset: Any) -> Dict[str, int]:
    provenance = dataset._metadata.get("provenance", {})
    directions = provenance.get("factor_directions", {}) if isinstance(provenance, Mapping) else {}
    if not isinstance(directions, Mapping):
        raise DatasetError(
            "factor_directions provenance must map factor names to +1/-1",
            code="INVALID_DATASET",
        )
    output = {}
    for factor, direction in directions.items():
        if (
            not isinstance(factor, str)
            or factor not in dataset._factor_names
            or type(direction) is not int
            or direction not in (-1, 1)
        ):
            raise DatasetError(
                "factor_directions provenance is invalid",
                code="INVALID_DATASET",
            )
        output[factor] = int(direction)
    missing = set(dataset._factor_names) - set(output)
    if missing:
        raise DatasetError(
            "dataset provenance is missing FactorSpec.direction for: %s"
            % ", ".join(sorted(missing)),
            code="INVALID_DATASET",
        )
    return output


def _normalized_spec(module: Any, dataset: Any, spec: Any) -> Any:
    values = _dataset_defaults(dataset)
    supplied = _spec_mapping(spec)
    values.update(supplied)
    explicit = values.get("direction_overrides") or {}
    if not isinstance(explicit, Mapping):
        raise ResearchConfigError(
            "direction_overrides must be a mapping",
            code="INVALID_CONFIG",
        )
    # FactorSpec.direction belongs to immutable dataset provenance. Keep the
    # evaluation config limited to caller overrides so configuration identity
    # does not accidentally absorb collection metadata.
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
    """Canonicalize hash-visible index metadata on a defensive evaluation copy.

    A DatetimeIndex's ``freq`` is derivable metadata: dataset persistence keeps
    the timestamps and their order, but CSV reconstruction cannot retain that
    cache. Research-window slicing can also leave unused warm-up dates in a
    MultiIndex level, while CSV reconstruction creates only the used levels.
    Fincore fingerprints pandas index metadata, so these caches must be
    canonicalized before passing a collected frame or its save/load copy.
    """
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
        return cast(
            BaseException,
            ResearchConfigError(
                str(exc),
                code=getattr(exc, "code", "INVALID_CONFIG"),
                report=getattr(exc, "report", None),
            ),
        )
    if dependency_cls is not None and isinstance(exc, dependency_cls):
        return cast(
            BaseException,
            DependencyError(
                str(exc),
                code=getattr(exc, "code", "DEPENDENCY_UNAVAILABLE"),
                report=getattr(exc, "report", None),
            ),
        )
    if quality_cls is not None and isinstance(exc, quality_cls):
        return cast(
            BaseException,
            DataQualityError(
                str(exc),
                code=getattr(exc, "code", "LOSS_LIMIT_EXCEEDED"),
                report=getattr(exc, "report", None),
            ),
        )
    if dataset_cls is not None and isinstance(exc, dataset_cls):
        return cast(
            BaseException,
            DatasetError(
                str(exc),
                code=getattr(exc, "code", "INVALID_DATASET"),
                report=getattr(exc, "report", None),
            ),
        )
    if computation_cls is not None and isinstance(exc, computation_cls):
        return cast(
            BaseException,
            FactorComputationError(
                str(exc),
                factor=getattr(exc, "factor", "fincore"),
                asset=getattr(exc, "asset", None),
                phase=getattr(exc, "phase", "evaluation"),
                code=getattr(exc, "code", "FACTOR_COMPUTATION_FAILED"),
                report=getattr(exc, "report", None),
            ),
        )
    return exc


def evaluate_dataset(dataset: Any, spec: Any = None, **kwargs: Any) -> Any:
    """Call fincore's public evaluator with a content-bound dataset snapshot.

    Callers may pass one mapping/dataclass ``spec`` or individual evaluation
    fields as keyword arguments. Combining the two forms is rejected so there
    is no implicit precedence rule between duplicate configuration sources.
    """
    if spec is not None and kwargs:
        raise ResearchConfigError(
            "pass either spec or evaluation keyword arguments, not both",
            code="INVALID_CONFIG",
        )
    if spec is None and kwargs:
        spec = kwargs
    module = _import_research_module()
    capabilities = _check_capabilities(module)
    normalized = _normalized_spec(module, dataset, spec)
    label = getattr(normalized, "label", None)
    available_labels = set(capabilities.get("labels", ()))
    if label not in available_labels:
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

    prices = None if label == "precomputed" else dataset.prices or None
    if prices is not None:
        prices = {
            name: _canonicalize_evaluation_index(frame, pandas) for name, frame in prices.items()
        }
    precomputed_returns = dataset.precomputed_returns if label == "precomputed" else None
    if precomputed_returns is not None:
        precomputed_returns = _canonicalize_evaluation_index(precomputed_returns, pandas)
    grid = _canonicalize_evaluation_index(dataset.grid, pandas)
    universe = _canonicalize_evaluation_index(dataset.universe, pandas)
    factors = _canonicalize_evaluation_index(dataset.raw_factors, pandas)
    factors.attrs["factor_directions"] = _factor_directions(dataset)
    factors.attrs["dataset_id"] = dataset.dataset_id
    factors.attrs["provenance"] = dataset.metadata.get("provenance", {})
    try:
        result = module.evaluate_factor_research(
            factors,
            grid=grid,
            prices=prices,
            universe=universe,
            groups=dataset.groups,
            precomputed_returns=precomputed_returns,
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


__all__ = ("evaluate_dataset",)
