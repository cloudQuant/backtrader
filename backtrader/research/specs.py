"""Immutable, validated configuration for FactorIndicator research runs."""

from __future__ import annotations

import hashlib
import inspect
import json
import marshal
import sys
from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Dict, Optional, Sequence, Tuple, Type

from .errors import ConfigError, DatasetError, DependencyError


def require_research_runtime() -> Any:
    """Return pandas or raise the typed minimum-runtime/dependency error.

    The import is intentionally delayed so importing ``backtrader.research``
    does not add pandas to the ordinary Backtrader import path.
    """
    if sys.version_info < (3, 11):
        raise DependencyError("Factor research requires Python 3.11 or newer")
    try:
        import pandas as pd
    except ImportError as exc:
        raise DependencyError("Factor research requires pandas") from exc
    return pd


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """Return mutable constructor values from recursively frozen spec values."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(thaw(item) for item in value)
    if isinstance(value, frozenset):
        return {thaw(item) for item in value}
    return value


def _nonempty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("%s must be a non-empty string" % field_name)
    return value


def _source_fingerprint(indicator: Type[Any]) -> Tuple[str, str, str]:
    """Fingerprint the class declaration and its containing algorithm module."""
    try:
        source = inspect.getsource(indicator).encode("utf-8")
    except (OSError, TypeError, IOError):
        pieces = []
        for name, member in sorted(indicator.__dict__.items()):
            function = (
                member.__func__ if isinstance(member, (classmethod, staticmethod)) else member
            )
            code = getattr(function, "__code__", None)
            if code is not None:
                pieces.append(name.encode("utf-8") + b"\0" + marshal.dumps(code))
        if not pieces:
            raise ConfigError(
                "factor source cannot be fingerprinted; define it in a Python source module"
            ) from None
        source = b"\0".join(pieces)
        class_kind = "python-bytecode-fallback"
    else:
        class_kind = "python-source"
    class_hash = hashlib.sha256(source).hexdigest()
    module_hash = ""
    module_kind = "python-module-unavailable"
    try:
        source_path = inspect.getsourcefile(indicator)
        if source_path:
            with open(source_path, "rb") as handle:
                module_source = handle.read()
            module_hash = hashlib.sha256(module_source).hexdigest()
            module_kind = "python-module-source"
    except (OSError, TypeError, IOError):
        pass
    combined = hashlib.sha256((class_hash + ":" + module_hash).encode("ascii")).hexdigest()
    return combined, module_hash, class_kind + "+" + module_kind


def _lookback(indicator: Type[Any], params: Mapping[str, Any]) -> int:
    declaration = getattr(indicator, "lookback_h", None)
    if declaration is None:
        raise ConfigError("factor %s must declare lookback_h" % indicator.__name__)
    try:
        value = declaration(**thaw(params)) if callable(declaration) else declaration
    except (TypeError, ValueError, NotImplementedError) as exc:
        raise ConfigError(
            "factor %s lookback_h declaration is invalid" % indicator.__name__
        ) from exc
    if type(value) is not int or value < 0:
        raise ConfigError("factor lookback_h must be a non-negative integer (not bool)")
    return value


def _validate_feed_binding(alias: Any, binding: Any) -> Tuple[str, Any]:
    _nonempty_string(alias, "field binding alias")

    def validate_source(source: Any) -> str:
        if not isinstance(source, str):
            raise ConfigError("direct binding source must be a qualified string")
        if source.startswith("feed:"):
            parts = source.split(":")
            if len(parts) != 3 or not parts[1] or not parts[2]:
                raise ConfigError("feed bindings must use 'feed:<name>:<line>'")
            return "feed"
        if source.startswith("table:"):
            parts = source.split(":")
            if len(parts) != 2 or not parts[1]:
                raise ConfigError("table bindings must use 'table:<name>'")
            return "table"
        raise ConfigError("direct binding source must use feed: or table:")

    if isinstance(binding, str):
        if binding.startswith("feed:"):
            parts = binding.split(":")
            if len(parts) != 3 or not parts[1] or not parts[2]:
                raise ConfigError("feed bindings must use 'feed:<name>:<line>'")
            return "feed", binding
        if binding.startswith("table:"):
            parts = binding.split(":")
            if len(parts) != 2 or not parts[1]:
                raise ConfigError("table bindings must use 'table:<name>'")
            return "table", binding
        raise ConfigError("field bindings must use 'feed:<name>:<line>' or 'table:<name>'")
    if not isinstance(binding, Mapping):
        raise ConfigError("field bindings must be qualified strings or descriptors")
    derive = binding.get("derive")
    if derive == "adv":
        if set(binding) != {"derive", "source", "window"}:
            raise ConfigError("derived ADV requires derive/source/window only")
        source = _nonempty_string(binding.get("source"), "ADV source")
        window = binding.get("window")
        if type(window) is not int or window < 1:
            raise ConfigError("derived ADV window must be a positive non-bool integer")
        if not alias.startswith("adv") or not alias[3:].isdigit() or int(alias[3:]) != window:
            raise ConfigError("derived ADV alias advN must match window N")
        if source != "dollar_volume":
            raise ConfigError("derived ADV must use dollar_volume")
        return "derive_adv", MappingProxyType(dict(binding))
    if derive == "vwap_volume":
        if set(binding) != {"derive", "vwap", "volume"}:
            raise ConfigError("derived dollar_volume requires derive/vwap/volume only")
        return "derive_vwap_volume", MappingProxyType(dict(binding))
    if binding.get("kind") == "direct":
        if set(binding) != {"kind", "source"}:
            raise ConfigError("direct binding requires kind/source only")
        direct_source = binding.get("source")
        if not isinstance(direct_source, str):
            raise ConfigError("direct binding source must be a qualified string")
        validate_source(direct_source)
        return "direct", MappingProxyType(dict(binding))
    raise ConfigError("unknown field binding descriptor")


@dataclass(frozen=True, init=False)
class FactorSpec:
    """One immutable named native factor declaration.

    ``lookback_h`` and ``source_sha256`` are derived and stored metadata, not
    caller-supplied overrides.  The value-only ``factors`` mapping accepted by
    :class:`FactorStrategy` is a convenience conversion into this object.
    """

    name: str
    indicator: Type[Any]
    panel_line: str
    params: Mapping[str, Any]
    field_bindings: Mapping[str, Any]
    classification_bindings: Mapping[str, str]
    operator_profile: str
    direction: int
    lookback_h: int
    source_sha256: str
    module_source_sha256: str
    source_hash_kind: str

    def __init__(
        self,
        name: str,
        indicator: Type[Any],
        panel_line: str,
        params: Optional[Mapping[str, Any]] = None,
        field_bindings: Optional[Mapping[str, Any]] = None,
        classification_bindings: Optional[Mapping[str, str]] = None,
        operator_profile: str = "alpha101-v1",
        direction: int = 1,
        **unsupported: Any,
    ) -> None:
        if unsupported:
            raise ConfigError("unsupported FactorSpec fields: %s" % sorted(unsupported))
        _nonempty_string(name, "factor name")
        _nonempty_string(panel_line, "panel_line")
        _nonempty_string(operator_profile, "operator_profile")
        if type(direction) is not int or direction not in (-1, 1):
            raise ConfigError("direction must be integer +1 or -1; bool is not accepted")
        if params is None:
            params = {}
        if field_bindings is None:
            field_bindings = {}
        if classification_bindings is None:
            classification_bindings = {}
        if not isinstance(params, Mapping):
            raise ConfigError("factor params must be a mapping")
        if not isinstance(field_bindings, Mapping):
            raise ConfigError("field_bindings must be a mapping")
        if not isinstance(classification_bindings, Mapping):
            raise ConfigError("classification_bindings must be a mapping")

        from .factor_indicator import FactorIndicator

        if not isinstance(indicator, type) or not issubclass(indicator, FactorIndicator):
            raise ConfigError("research factors must be FactorIndicator subclasses")
        if indicator is FactorIndicator or getattr(indicator, "_factor_bound", False):
            raise ConfigError("FactorSpec requires an unbound concrete FactorIndicator class")
        if getattr(indicator, "panel_mode", None) != "next":
            raise ConfigError("FactorSpec requires panel_mode='next'")
        if any(
            name in base.__dict__ for base in indicator.__mro__ for name in ("build", "expression")
        ):
            raise ConfigError("build/expression declarations are not supported in iteration 45")
        declared = tuple(indicator._factor_template_names())
        if panel_line not in declared:
            raise ConfigError("panel_line must select a declared output template")

        frozen_params = _freeze(dict(params))
        declared_fields = tuple(getattr(indicator, "formula_fields", ()))
        declared_classifications = tuple(getattr(indicator, "classification_fields", ()))
        if any(not isinstance(item, str) or not item for item in declared_fields):
            raise ConfigError("formula_fields must contain non-empty strings")
        if len(set(declared_fields)) != len(declared_fields):
            raise ConfigError("formula_fields must not contain duplicates")
        if any(not isinstance(item, str) or not item for item in declared_classifications):
            raise ConfigError("classification_fields must contain non-empty strings")
        frozen_fields: Dict[str, Any] = {}
        for alias, binding in field_bindings.items():
            _, normalized = _validate_feed_binding(alias, binding)
            frozen_fields[alias] = normalized
            if alias not in declared_fields:
                raise ConfigError("field binding %s is not declared in formula_fields" % alias)
        for alias, binding in frozen_fields.items():
            if isinstance(binding, Mapping) and binding.get("derive") == "adv":
                source = binding["source"]
                source_binding = frozen_fields.get(source)
                if source_binding is None:
                    raise ConfigError("derived ADV requires an explicit dollar_volume binding")
                if isinstance(source_binding, Mapping) and source_binding.get("derive") not in (
                    None,
                    "vwap_volume",
                ):
                    raise ConfigError("derived ADV source uses an unsupported derivation")
                if isinstance(source_binding, str) and source_binding.startswith("table:"):
                    raise ConfigError("derived ADV source must be a dollar_volume feed line")
                if isinstance(source_binding, Mapping) and source_binding.get("kind") == "direct":
                    selected = str(source_binding.get("source", "")).rsplit(":", 1)[-1]
                    if selected != "dollar_volume":
                        raise ConfigError("derived ADV source binding must select dollar_volume")
        for alias, binding in frozen_fields.items():
            if isinstance(binding, Mapping) and binding.get("derive") == "vwap_volume":
                if alias != "dollar_volume":
                    raise ConfigError("vwap_volume derivation only defines dollar_volume")
                if not {"vwap", "volume"}.issubset(set(declared_fields)):
                    raise ConfigError("vwap_volume derivation requires vwap/volume formula fields")
                if "vwap" not in frozen_fields or "volume" not in frozen_fields:
                    raise ConfigError("vwap_volume derivation requires vwap/volume bindings")
        frozen_classifications: Dict[str, str] = {}
        for alias, binding in classification_bindings.items():
            _nonempty_string(alias, "classification alias")
            if alias not in declared_classifications and alias not in tuple(
                getattr(indicator, "classification_levels", ())
            ):
                raise ConfigError("classification binding %s is not declared by factor" % alias)
            classification_source = _nonempty_string(binding, "classification binding")
            if classification_source.startswith("feed:"):
                raise ConfigError(
                    "classification bindings require a named PIT table with taxonomy metadata"
                )
            if classification_source.startswith("table:"):
                parts = classification_source.split(":")
                if len(parts) != 2 or not parts[1]:
                    raise ConfigError("classification table bindings must use table:<name>")
            elif ":" in classification_source:
                raise ConfigError("classification bindings must use a named table")
            # A bare non-empty name is an explicit ResearchSpec classification
            # table key. FactorStrategy resolves it against that named mapping.
            frozen_classifications[alias] = classification_source

        lookback = _lookback(indicator, frozen_params)
        source_sha256, module_source_sha256, source_hash_kind = _source_fingerprint(indicator)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "indicator", indicator)
        object.__setattr__(self, "panel_line", panel_line)
        object.__setattr__(self, "params", frozen_params)
        object.__setattr__(self, "field_bindings", MappingProxyType(frozen_fields))
        object.__setattr__(
            self, "classification_bindings", MappingProxyType(frozen_classifications)
        )
        object.__setattr__(self, "operator_profile", operator_profile)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "lookback_h", lookback)
        object.__setattr__(self, "source_sha256", source_sha256)
        object.__setattr__(self, "module_source_sha256", module_source_sha256)
        object.__setattr__(self, "source_hash_kind", source_hash_kind)

    @classmethod
    def from_mapping(cls, name: str, value: Mapping[str, Any]) -> "FactorSpec":
        if not isinstance(value, Mapping):
            raise ConfigError("factor %s must be a FactorSpec or mapping" % name)
        fields = set(value)
        allowed = {
            "name",
            "indicator",
            "params",
            "panel_line",
            "field_bindings",
            "classification_bindings",
            "operator_profile",
            "direction",
        }
        unknown = fields - allowed
        if unknown:
            raise ConfigError("unsupported FactorSpec fields: %s" % sorted(unknown))
        if "indicator" not in value:
            raise ConfigError("factor %s requires indicator" % name)
        if "panel_line" not in value:
            raise ConfigError("factor %s requires panel_line" % name)
        declared_name = value.get("name", name)
        if declared_name != name:
            raise ConfigError("factor mapping key must match FactorSpec.name")
        return cls(
            name=name,
            indicator=value["indicator"],
            panel_line=value["panel_line"],
            params=value.get("params", {}),
            field_bindings=value.get("field_bindings", {}),
            classification_bindings=value.get("classification_bindings", {}),
            operator_profile=value.get("operator_profile", "alpha101-v1"),
            direction=value.get("direction", 1),
        )

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "indicator_module": self.indicator.__module__,
            "indicator_qualname": self.indicator.__qualname__,
            "panel_mode": self.indicator.panel_mode,
            "panel_line": self.panel_line,
            "params": thaw(self.params),
            "field_bindings": dict(self.field_bindings),
            "classification_bindings": dict(self.classification_bindings),
            "operator_profile": self.operator_profile,
            "direction": self.direction,
            "lookback_h": self.lookback_h,
            "source_sha256": self.source_sha256,
            "module_source_sha256": self.module_source_sha256,
            "source_hash_kind": self.source_hash_kind,
        }


def normalize_factor_specs(
    factors: Any,
) -> Mapping[str, FactorSpec]:
    """Convert the one-time mapping convenience and reject duplicate names."""
    if isinstance(factors, Mapping):
        items = list(factors.items())
    elif isinstance(factors, (tuple, list)):
        items = []
        for item in factors:
            if isinstance(item, FactorSpec):
                items.append((item.name, item))
            elif isinstance(item, (tuple, list)) and len(item) == 2:
                items.append((item[0], item[1]))
            else:
                raise ConfigError("factors must contain FactorSpec objects or name/value pairs")
    else:
        raise ConfigError("factors must be a non-empty mapping or sequence")
    if not items:
        raise ConfigError("at least one factor is required")

    result: Dict[str, FactorSpec] = {}
    for name, value in items:
        _nonempty_string(name, "factor mapping key")
        if name in result:
            raise ConfigError("duplicate factor name: %s" % name)
        if isinstance(value, FactorSpec):
            if value.name != name:
                raise ConfigError("factor mapping key must match FactorSpec.name")
            result[name] = value
        else:
            result[name] = FactorSpec.from_mapping(name, value)
    return MappingProxyType(result)


def _timestamp(value: Any, field_name: str, pd: Any) -> Any:
    if isinstance(value, str):
        try:
            stamp = pd.Timestamp(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError("%s must be an ISO8601 timestamp" % field_name) from exc
    elif isinstance(value, datetime):
        stamp = pd.Timestamp(value)
    else:
        raise ConfigError("%s must be a timezone-aware Timestamp or ISO8601 string" % field_name)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ConfigError("%s must include a timezone" % field_name)
    return stamp.tz_convert("UTC")


def _utc_index(index: Any, field_name: str, pd: Any) -> Any:
    if not isinstance(index, pd.DatetimeIndex):
        raise ConfigError("%s must be a DatetimeIndex" % field_name)
    if index.tz is None:
        raise ConfigError("%s must be timezone-aware UTC" % field_name)
    try:
        converted = index.tz_convert("UTC")
    except (TypeError, ValueError) as exc:
        raise ConfigError("%s must use UTC timestamps" % field_name) from exc
    if any(stamp.utcoffset() != timedelta(0) for stamp in index.to_pydatetime()):
        raise ConfigError("%s must use UTC (zero offset)" % field_name)
    return converted


def _copy_input_table(name: str, table: Any, pd: Any, *, classification: bool) -> Any:
    if not isinstance(table, pd.DataFrame):
        raise ConfigError("input %s must be a pandas DataFrame" % name)
    if not isinstance(table.index, pd.MultiIndex) or tuple(table.index.names) != (
        "time",
        "asset",
    ):
        raise ConfigError("input %s index must be named (time, asset)" % name)
    if not table.index.is_unique:
        raise DatasetError("input %s contains duplicate (time, asset) keys" % name)
    if classification:
        required = {"level", "category", "effective_at", "available_at", "taxonomy_version"}
    else:
        required = {"value", "available_at", "data_version"}
    missing = required - set(table.columns)
    if missing:
        raise DatasetError(
            "input %s is missing required columns" % name,
            code="MISSING_INPUT",
            report={"input": name, "missing_columns": tuple(sorted(missing))},
        )
    copied = table.copy(deep=True)
    # pandas copies frame attrs on current supported releases, but the public
    # metadata contract must not depend on that implementation detail.
    copied.attrs = deepcopy(table.attrs)
    return copied


@dataclass(frozen=True, init=False)
class ResearchSpec:
    """Immutable research calendar, target universe, and point-in-time inputs.

    DataFrame and Series inputs are copied on construction and returned as
    defensive copies.  ``grid`` is caller-supplied: this object never infers a
    calendar from a Feed or weekday sequence.
    """

    _grid: Any = field(repr=False, compare=False)
    start: Any
    end: Any
    targets: Tuple[str, ...]
    source_timezone: str
    snapshot_id: str
    price_basis: str
    calendar_id: str
    frequency: str
    feed_time_kind: str
    _groups: Mapping[str, str] = field(repr=False, compare=False)
    _universe: Any = field(repr=False, compare=False)
    _formula_universe: Any = field(repr=False, compare=False)
    _formula_fields: Mapping[str, Any] = field(repr=False, compare=False)
    _classifications: Mapping[str, Any] = field(repr=False, compare=False)
    universe_defaulted: bool
    formula_universe_defaulted: bool

    def __init__(
        self,
        *,
        grid: Any,
        start: Any,
        end: Any,
        targets: Sequence[str],
        source_timezone: str,
        snapshot_id: str,
        price_basis: str,
        calendar_id: str,
        frequency: str,
        feed_time_kind: str = "close_time",
        groups: Optional[Mapping[str, str]] = None,
        universe: Any = None,
        formula_universe: Any = None,
        formula_fields: Optional[Mapping[str, Any]] = None,
        classifications: Optional[Mapping[str, Any]] = None,
        **unsupported: Any,
    ) -> None:
        if unsupported:
            raise ConfigError("unsupported ResearchSpec fields: %s" % sorted(unsupported))
        pd = require_research_runtime()
        if not isinstance(grid, pd.DataFrame):
            raise ConfigError("grid must be a pandas DataFrame")
        grid_copy = grid.copy(deep=True)
        if (
            not isinstance(grid_copy.index, pd.DatetimeIndex)
            or grid_copy.index.name != "close_time"
        ):
            raise ConfigError("grid index must be a DatetimeIndex named 'close_time'")
        index = _utc_index(grid_copy.index, "grid index", pd)
        if not index.is_unique or not index.is_monotonic_increasing:
            raise ConfigError("grid close_time must be unique and strictly increasing")
        grid_copy.index = index
        if "open_time" not in grid_copy.columns:
            raise ConfigError("grid requires an open_time column")
        open_times = pd.DatetimeIndex(pd.to_datetime(grid_copy["open_time"], errors="coerce"))
        if open_times.isna().any() or open_times.tz is None:
            raise ConfigError("grid open_time values must be timezone-aware UTC datetimes")
        open_times_utc = _utc_index(open_times, "grid open_time", pd)
        if any(open_time > close_time for open_time, close_time in zip(open_times_utc, index)):
            raise ConfigError("grid open_time must not follow its close_time")
        grid_copy["open_time"] = open_times_utc

        start_utc = _timestamp(start, "start", pd)
        end_utc = _timestamp(end, "end", pd)
        if start_utc > end_utc:
            raise ConfigError("start must not follow end")
        if start_utc not in index or end_utc not in index:
            raise ConfigError("start and end must be exact grid close_time endpoints")

        if not isinstance(targets, (tuple, list)) or not targets:
            raise ConfigError("targets must be a non-empty tuple/list of asset names")
        normalized_targets = tuple(_nonempty_string(value, "target") for value in targets)
        if len(set(normalized_targets)) != len(normalized_targets):
            raise ConfigError("target names must be unique")
        source_timezone = _nonempty_string(source_timezone, "source_timezone")
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(source_timezone)
        except (ImportError, KeyError, ValueError) as exc:
            raise ConfigError("source_timezone must be a valid IANA timezone") from exc

        snapshot_id = _nonempty_string(snapshot_id, "snapshot_id")
        price_basis = _nonempty_string(price_basis, "price_basis")
        if price_basis.strip().lower() in {"default", "unknown", "unspecified"}:
            raise ConfigError("price_basis must describe an explicit price convention")
        calendar_id = _nonempty_string(calendar_id, "calendar_id")
        frequency = _nonempty_string(frequency, "frequency")
        if feed_time_kind != "close_time":
            raise ConfigError("feed_time_kind currently supports only 'close_time'")

        if groups is None:
            normalized_groups = dict.fromkeys(normalized_targets, "default")
        elif isinstance(groups, Mapping):
            if set(groups) != set(normalized_targets):
                raise ConfigError("groups must cover exactly all target assets")
            normalized_groups = {
                asset: _nonempty_string(groups[asset], "group") for asset in normalized_targets
            }
        else:
            raise ConfigError("groups must be an asset-to-group mapping")

        study_index = index[(index >= start_utc) & (index <= end_utc)]
        formula_index = index[index <= end_utc]
        study_keys = pd.MultiIndex.from_product(
            [study_index, normalized_targets], names=("time", "asset")
        )
        formula_keys = pd.MultiIndex.from_product(
            [formula_index, normalized_targets], names=("time", "asset")
        )
        universe_defaulted = universe is None
        normalized_universe = self._normalize_bool_index(
            universe,
            study_keys,
            default=universe_defaulted,
            pd=pd,
            field_name="universe",
        )
        formula_defaulted = formula_universe is None
        normalized_formula = self._normalize_bool_index(
            formula_universe,
            formula_keys,
            default=formula_defaulted,
            pd=pd,
            field_name="formula_universe",
        )

        if formula_fields is None:
            formula_fields = {}
        if classifications is None:
            classifications = {}
        if not isinstance(formula_fields, Mapping) or not isinstance(classifications, Mapping):
            raise ConfigError("formula_fields and classifications must be mappings")
        normalized_fields = {
            _nonempty_string(name, "formula field name"): _copy_input_table(
                name, table, pd, classification=False
            )
            for name, table in formula_fields.items()
        }
        normalized_classifications = {
            _nonempty_string(name, "classification binding name"): _copy_input_table(
                name, table, pd, classification=True
            )
            for name, table in classifications.items()
        }

        object.__setattr__(self, "_grid", grid_copy)
        object.__setattr__(self, "start", start_utc)
        object.__setattr__(self, "end", end_utc)
        object.__setattr__(self, "targets", normalized_targets)
        object.__setattr__(self, "source_timezone", source_timezone)
        object.__setattr__(self, "snapshot_id", snapshot_id)
        object.__setattr__(self, "price_basis", price_basis)
        object.__setattr__(self, "calendar_id", calendar_id)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "feed_time_kind", feed_time_kind)
        object.__setattr__(self, "_groups", MappingProxyType(normalized_groups))
        object.__setattr__(self, "_universe", normalized_universe)
        object.__setattr__(self, "_formula_universe", normalized_formula)
        object.__setattr__(self, "_formula_fields", MappingProxyType(normalized_fields))
        object.__setattr__(self, "_classifications", MappingProxyType(normalized_classifications))
        object.__setattr__(self, "universe_defaulted", universe_defaulted)
        object.__setattr__(self, "formula_universe_defaulted", formula_defaulted)

    @staticmethod
    def _normalize_bool_index(
        value: Any,
        expected_index: Any,
        *,
        default: bool,
        pd: Any,
        field_name: str,
    ) -> Any:
        if value is None:
            return pd.Series(True, index=expected_index, dtype=bool, name=field_name)
        if not isinstance(value, pd.Series):
            raise ConfigError("%s must be a boolean Series indexed by (time, asset)" % field_name)
        result = value.copy(deep=True)
        if not isinstance(result.index, pd.MultiIndex) or tuple(result.index.names) != (
            "time",
            "asset",
        ):
            raise ConfigError("%s index must be named (time, asset)" % field_name)
        if not result.index.is_unique:
            raise DatasetError(
                "%s contains duplicate keys" % field_name,
                code="UNKNOWN_UNIVERSE",
                report={
                    "field": field_name,
                    "duplicate_count": int(result.index.duplicated().sum()),
                },
            )
        if not pd.api.types.is_bool_dtype(result.dtype) or result.isna().any():
            raise DatasetError(
                "%s must contain non-missing boolean values" % field_name,
                code="UNKNOWN_UNIVERSE",
                report={"field": field_name, "missing_count": int(result.isna().sum())},
            )
        expected = set(expected_index.tolist())
        actual = set(result.index.tolist())
        missing = expected - actual
        extra = actual - expected
        if missing or extra:
            raise DatasetError(
                "%s must cover exactly the required time/asset keys" % field_name,
                code="UNKNOWN_UNIVERSE",
                report={
                    "field": field_name,
                    "missing_count": len(missing),
                    "extra_count": len(extra),
                },
            )
        return result.reindex(expected_index).astype(bool).rename(field_name)

    @property
    def grid(self) -> Any:
        return self._grid.copy(deep=True)

    @property
    def groups(self) -> Mapping[str, str]:
        return self._groups

    @property
    def universe(self) -> Any:
        return self._universe.copy(deep=True)

    @property
    def formula_universe(self) -> Any:
        return self._formula_universe.copy(deep=True)

    @property
    def formula_fields(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {name: frame.copy(deep=True) for name, frame in self._formula_fields.items()}
        )

    @property
    def classifications(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {name: frame.copy(deep=True) for name, frame in self._classifications.items()}
        )

    @property
    def calculation_grid(self) -> Any:
        """Full warm-up through research-end grid, excluding the label tail."""
        return self._grid.loc[self._grid.index <= self.end].copy(deep=True)

    @property
    def research_grid(self) -> Any:
        return self._grid.loc[
            (self._grid.index >= self.start) & (self._grid.index <= self.end)
        ].copy(deep=True)

    @property
    def grid_sha256(self) -> str:
        rows = [
            (close_time.isoformat(), open_time.isoformat())
            for close_time, open_time in zip(self._grid.index, self._grid["open_time"])
        ]
        payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "targets": self.targets,
            "groups": dict(self._groups),
            "source_timezone": self.source_timezone,
            "snapshot_id": self.snapshot_id,
            "price_basis": self.price_basis,
            "calendar_id": self.calendar_id,
            "frequency": self.frequency,
            "feed_time_kind": self.feed_time_kind,
            "grid_sha256": self.grid_sha256,
            "universe_defaulted": self.universe_defaulted,
            "formula_universe_defaulted": self.formula_universe_defaulted,
            "formula_fields": tuple(sorted(self._formula_fields)),
            "classifications": tuple(sorted(self._classifications)),
        }


__all__ = (
    "FactorSpec",
    "ResearchSpec",
    "normalize_factor_specs",
    "require_research_runtime",
    "thaw",
)
