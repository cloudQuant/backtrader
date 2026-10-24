"""Immutable, validated configuration for FactorIndicator research runs.

The research boundary is deliberately small: a caller-supplied UTC grid, the
target list, optional group/universe facts and per-factor field bindings to
ordinary feed lines.  Point-in-time tables, as-of selection, classification
taxonomies and ``table:`` bindings are not part of this API; any extra numeric
input (industry code, cap, VWAP, ...) is an ordinary aligned feed line.
"""

from __future__ import annotations

import hashlib
import inspect
import marshal
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Dict, Optional, Sequence, Tuple, Type

from ..errors import ResearchConfigError, DatasetError, DependencyError


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
        raise ResearchConfigError("%s must be a non-empty string" % field_name)
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
            raise ResearchConfigError(
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
        raise ResearchConfigError("factor %s must declare lookback_h" % indicator.__name__)
    try:
        value = declaration(**thaw(params)) if callable(declaration) else declaration
    except (TypeError, ValueError, NotImplementedError) as exc:
        raise ResearchConfigError(
            "factor %s lookback_h declaration is invalid" % indicator.__name__
        ) from exc
    if type(value) is not int or value < 0:
        raise ResearchConfigError("factor lookback_h must be a non-negative integer (not bool)")
    return value


@dataclass(frozen=True)
class FactorHistoryContract:
    # Factor-authored statement of how a finite source prefix reconstructs state.
    # finite_window covers the executed graph; replay_from_source_origin requires
    # an exact adapter-declared origin and a contiguous validated cohort prefix.

    kind: str
    span_bars: Optional[int] = None

    def __post_init__(self) -> None:
        if self.kind == "finite_window":
            if type(self.span_bars) is not int or self.span_bars < 1:
                raise ResearchConfigError(
                    "finite_window history contract requires positive span_bars"
                )
        elif self.kind == "replay_from_source_origin":
            if self.span_bars is not None:
                raise ResearchConfigError("replay_from_source_origin does not accept span_bars")
        else:
            raise ResearchConfigError("unknown factor history contract kind")

    @classmethod
    def finite_window(cls, span_bars: int) -> "FactorHistoryContract":
        # Declare that factor state depends on at most span_bars rows.
        return cls("finite_window", span_bars)

    @classmethod
    def replay_from_source_origin(cls) -> "FactorHistoryContract":
        # Declare that factor state must replay from an adapter-declared origin.
        return cls("replay_from_source_origin")

    def to_metadata(self) -> Dict[str, Any]:
        return {"kind": self.kind, "span_bars": self.span_bars}


def _validate_feed_binding(alias: Any, binding: Any) -> Tuple[str, Any]:
    _nonempty_string(alias, "field binding alias")

    def validate_feed_source(source: Any) -> str:
        if not isinstance(source, str) or not source.startswith("feed:"):
            raise ResearchConfigError(
                "field binding sources must use 'feed:<name>:<line>'; PIT/table bindings "
                "are not part of this API"
            )
        parts = source.split(":")
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise ResearchConfigError("feed bindings must use 'feed:<name>:<line>'")
        return source

    if isinstance(binding, str):
        validate_feed_source(binding)
        return "feed", binding
    if not isinstance(binding, Mapping):
        raise ResearchConfigError("field bindings must be qualified strings or descriptors")
    derive = binding.get("derive")
    if derive == "adv":
        if set(binding) != {"derive", "source", "window"}:
            raise ResearchConfigError("derived ADV requires derive/source/window only")
        source = _nonempty_string(binding.get("source"), "ADV source")
        window = binding.get("window")
        if type(window) is not int or window < 1:
            raise ResearchConfigError("derived ADV window must be a positive non-bool integer")
        if not alias.startswith("adv") or not alias[3:].isdigit() or int(alias[3:]) != window:
            raise ResearchConfigError("derived ADV alias advN must match window N")
        if source != "dollar_volume":
            raise ResearchConfigError("derived ADV must use dollar_volume")
        return "derive_adv", MappingProxyType(dict(binding))
    if derive == "vwap_volume":
        if set(binding) != {"derive", "vwap", "volume"}:
            raise ResearchConfigError("derived dollar_volume requires derive/vwap/volume only")
        return "derive_vwap_volume", MappingProxyType(dict(binding))
    if binding.get("kind") == "direct":
        if set(binding) != {"kind", "source"}:
            raise ResearchConfigError("direct binding requires kind/source only")
        validate_feed_source(binding.get("source"))
        return "direct", MappingProxyType(dict(binding))
    raise ResearchConfigError("unknown field binding descriptor")


@dataclass(frozen=True, init=False)
class FactorSpec:
    """One immutable named native or expression factor declaration.

    ``lookback_h`` and ``source_sha256`` are derived and stored metadata, not
    caller-supplied overrides.  The value-only ``factors`` mapping accepted by
    :class:`FactorStrategy` is a convenience conversion into this object.
    """

    name: str
    indicator: Type[Any]
    panel_line: str
    params: Mapping[str, Any]
    field_bindings: Mapping[str, Any]
    operator_profile: str
    direction: int
    mode: str
    lookback_h: int
    source_sha256: str
    module_source_sha256: str
    source_hash_kind: str
    history_contract: Optional[FactorHistoryContract]

    def __init__(
        self,
        name: str,
        indicator: Type[Any],
        panel_line: str,
        params: Optional[Mapping[str, Any]] = None,
        field_bindings: Optional[Mapping[str, Any]] = None,
        operator_profile: str = "alpha101-v2",
        direction: int = 1,
        mode: Optional[str] = None,
        **unsupported: Any,
    ) -> None:
        if unsupported:
            raise ResearchConfigError("unsupported FactorSpec fields: %s" % sorted(unsupported))
        _nonempty_string(name, "factor name")
        _nonempty_string(panel_line, "panel_line")
        _nonempty_string(operator_profile, "operator_profile")
        if type(direction) is not int or direction not in (-1, 1):
            raise ResearchConfigError("direction must be integer +1 or -1; bool is not accepted")
        if params is None:
            params = {}
        if field_bindings is None:
            field_bindings = {}
        if not isinstance(params, Mapping):
            raise ResearchConfigError("factor params must be a mapping")
        if "mode" in params:
            raise ResearchConfigError(
                "factor mode must be selected with FactorSpec(mode=...), not params['mode']"
            )
        if not isinstance(field_bindings, Mapping):
            raise ResearchConfigError("field_bindings must be a mapping")

        from .factor_indicator import FactorIndicator

        if not isinstance(indicator, type) or not issubclass(indicator, FactorIndicator):
            raise ResearchConfigError("research factors must be FactorIndicator subclasses")
        if indicator is FactorIndicator or getattr(indicator, "_factor_bound", False):
            raise ResearchConfigError(
                "FactorSpec requires an unbound concrete FactorIndicator class"
            )
        history_contract = indicator.__dict__.get("history_contract")
        if history_contract is not None and type(history_contract) is not FactorHistoryContract:
            raise ResearchConfigError(
                "history_contract must be a class-authored FactorHistoryContract"
            )
        try:
            indicator._validate_factor_declaration()
            selected_mode = indicator._resolve_factor_mode(mode)
        except (TypeError, ValueError) as exc:
            raise ResearchConfigError("invalid factor declaration: %s" % exc) from exc
        except NotImplementedError as exc:
            raise ResearchConfigError("unsupported factor mode: %s" % exc) from exc
        resolved_params = indicator._resolve_factor_params(params)
        declared = tuple(indicator._factor_template_names())
        if panel_line not in declared:
            raise ResearchConfigError("panel_line must select a declared output template")

        frozen_params = _freeze(dict(params))
        declared_fields = tuple(getattr(indicator, "formula_fields", ()))
        if any(not isinstance(item, str) or not item for item in declared_fields):
            raise ResearchConfigError("formula_fields must contain non-empty strings")
        if len(set(declared_fields)) != len(declared_fields):
            raise ResearchConfigError("formula_fields must not contain duplicates")
        frozen_fields: Dict[str, Any] = {}
        for alias, binding in field_bindings.items():
            _, normalized = _validate_feed_binding(alias, binding)
            frozen_fields[alias] = normalized
            if alias not in declared_fields:
                raise ResearchConfigError(
                    "field binding %s is not declared in formula_fields" % alias
                )
        missing = set(declared_fields) - set(frozen_fields)
        if missing:
            raise DatasetError(
                "factor is missing explicit field bindings: %s" % sorted(missing),
                code="MISSING_INPUT",
                report={"factor": name, "missing_fields": tuple(sorted(missing))},
            )
        for alias, binding in frozen_fields.items():
            if isinstance(binding, Mapping) and binding.get("derive") == "adv":
                source = binding["source"]
                source_binding = frozen_fields.get(source)
                if source_binding is None:
                    raise ResearchConfigError(
                        "derived ADV requires an explicit dollar_volume binding"
                    )
                if isinstance(source_binding, Mapping) and source_binding.get("derive") not in (
                    None,
                    "vwap_volume",
                ):
                    raise ResearchConfigError("derived ADV source uses an unsupported derivation")
                if isinstance(source_binding, Mapping) and source_binding.get("kind") == "direct":
                    selected = str(source_binding.get("source", "")).rsplit(":", 1)[-1]
                    if selected != "dollar_volume":
                        raise ResearchConfigError(
                            "derived ADV source binding must select dollar_volume"
                        )
        for alias, binding in frozen_fields.items():
            if isinstance(binding, Mapping) and binding.get("derive") == "vwap_volume":
                if alias != "dollar_volume":
                    raise ResearchConfigError("vwap_volume derivation only defines dollar_volume")
                if not {"vwap", "volume"}.issubset(set(declared_fields)):
                    raise ResearchConfigError(
                        "vwap_volume derivation requires vwap/volume formula fields"
                    )
                if "vwap" not in frozen_fields or "volume" not in frozen_fields:
                    raise ResearchConfigError(
                        "vwap_volume derivation requires vwap/volume bindings"
                    )

        lookback = _lookback(indicator, resolved_params)
        source_sha256, module_source_sha256, source_hash_kind = _source_fingerprint(indicator)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "indicator", indicator)
        object.__setattr__(self, "panel_line", panel_line)
        object.__setattr__(self, "params", frozen_params)
        object.__setattr__(self, "field_bindings", MappingProxyType(frozen_fields))
        object.__setattr__(self, "operator_profile", operator_profile)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "mode", selected_mode)
        object.__setattr__(self, "lookback_h", lookback)
        object.__setattr__(self, "source_sha256", source_sha256)
        object.__setattr__(self, "module_source_sha256", module_source_sha256)
        object.__setattr__(self, "source_hash_kind", source_hash_kind)
        object.__setattr__(self, "history_contract", history_contract)

    @classmethod
    def from_mapping(cls, name: str, value: Mapping[str, Any]) -> "FactorSpec":
        if not isinstance(value, Mapping):
            raise ResearchConfigError("factor %s must be a FactorSpec or mapping" % name)
        fields = set(value)
        allowed = {
            "name",
            "indicator",
            "params",
            "panel_line",
            "field_bindings",
            "operator_profile",
            "direction",
            "mode",
        }
        unknown = fields - allowed
        if unknown:
            raise ResearchConfigError("unsupported FactorSpec fields: %s" % sorted(unknown))
        if "indicator" not in value:
            raise ResearchConfigError("factor %s requires indicator" % name)
        if "panel_line" not in value:
            raise ResearchConfigError("factor %s requires panel_line" % name)
        declared_name = value.get("name", name)
        if declared_name != name:
            raise ResearchConfigError("factor mapping key must match FactorSpec.name")
        return cls(
            name=name,
            indicator=value["indicator"],
            panel_line=value["panel_line"],
            params=value.get("params", {}),
            field_bindings=value.get("field_bindings", {}),
            operator_profile=value.get("operator_profile", "alpha101-v2"),
            direction=value.get("direction", 1),
            mode=value.get("mode"),
        )

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "indicator_module": self.indicator.__module__,
            "indicator_qualname": self.indicator.__qualname__,
            "mode": self.mode,
            "panel_mode": "next" if self.mode == "native" else "expression",
            "panel_line": self.panel_line,
            "params": thaw(self.params),
            "field_bindings": thaw(self.field_bindings),
            "operator_profile": self.operator_profile,
            "direction": self.direction,
            "lookback_h": self.lookback_h,
            "source_sha256": self.source_sha256,
            "module_source_sha256": self.module_source_sha256,
            "source_hash_kind": self.source_hash_kind,
            "history_contract": (
                None if self.history_contract is None else self.history_contract.to_metadata()
            ),
        }


def normalize_factor_specs(factors: Any) -> Mapping[str, FactorSpec]:
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
                raise ResearchConfigError(
                    "factors must contain FactorSpec objects or name/value pairs"
                )
    else:
        raise ResearchConfigError("factors must be a non-empty mapping or sequence")
    if not items:
        raise ResearchConfigError("at least one factor is required")

    result: Dict[str, FactorSpec] = {}
    for name, value in items:
        _nonempty_string(name, "factor mapping key")
        if name in result:
            raise ResearchConfigError("duplicate factor name: %s" % name)
        if isinstance(value, FactorSpec):
            if value.name != name:
                raise ResearchConfigError("factor mapping key must match FactorSpec.name")
            result[name] = value
        else:
            result[name] = FactorSpec.from_mapping(name, value)
    return MappingProxyType(result)


def _timestamp(value: Any, field_name: str, pd: Any) -> Any:
    if isinstance(value, str):
        try:
            stamp = pd.Timestamp(value)
        except (TypeError, ValueError) as exc:
            raise ResearchConfigError("%s must be an ISO8601 timestamp" % field_name) from exc
    elif isinstance(value, datetime):
        stamp = pd.Timestamp(value)
    else:
        raise ResearchConfigError(
            "%s must be a timezone-aware Timestamp or ISO8601 string" % field_name
        )
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ResearchConfigError("%s must include a timezone" % field_name)
    return stamp.tz_convert("UTC")


def _datetime_index_signature(index: Any) -> Tuple[bytes, str, Optional[str], str]:
    unit = getattr(index, "unit", None)
    return (
        index.asi8.tobytes(),
        str(index.dtype),
        None if unit is None else str(unit),
        str(index.tz),
    )


def _utc_index(index: Any, field_name: str, pd: Any) -> Any:
    if not isinstance(index, pd.DatetimeIndex):
        raise ResearchConfigError("%s must be a DatetimeIndex" % field_name)
    if index.tz is None:
        raise ResearchConfigError("%s must be timezone-aware UTC" % field_name)
    try:
        converted = index.tz_convert("UTC")
    except (TypeError, ValueError) as exc:
        raise ResearchConfigError("%s must use UTC timestamps" % field_name) from exc
    if any(stamp.utcoffset() != timedelta(0) for stamp in index.to_pydatetime()):
        raise ResearchConfigError("%s must use UTC (zero offset)" % field_name)
    return converted


def _copy_frame_with_owned_index(frame: Any) -> Any:
    """Copy a DataFrame and detach its immutable-looking index storage too."""
    copied = frame.copy(deep=True)
    copied.index = copied.index.copy(deep=True)
    return copied


def _grid_sha256(grid: Any) -> str:
    """Hash the canonical grid JSON without materializing all rows at once."""
    digest = hashlib.sha256()
    digest.update(b"[")
    first = True
    for close_time, open_time in zip(grid.index, grid["open_time"]):
        if not first:
            digest.update(b",")
        first = False

        # Timestamp.isoformat() only emits ASCII ISO-8601 characters, so these
        # quoted strings have the same JSON representation as json.dumps(...)
        # with ensure_ascii=False and compact separators.
        digest.update(b'["')
        digest.update(close_time.isoformat().encode("utf-8"))
        digest.update(b'","')
        digest.update(open_time.isoformat().encode("utf-8"))
        digest.update(b'"]')
    digest.update(b"]")
    return digest.hexdigest()


@dataclass(frozen=True, init=False)
class ResearchSpec:
    """Immutable research calendar, target universe and optional group facts.

    DataFrame and Series inputs are copied on construction and returned as
    defensive copies.  ``grid`` is caller-supplied: this object never infers a
    calendar from a Feed or weekday sequence.
    """

    _grid: Any = field(repr=False, compare=False)
    _grid_sha256: str = field(repr=False, compare=False)
    _feed_datetime_nums: Tuple[float, ...] = field(repr=False, compare=False)
    _feed_datetime_index_signature: Tuple[bytes, str, Optional[str], str] = field(
        repr=False, compare=False
    )
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
    universe_defaulted: bool

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
        **unsupported: Any,
    ) -> None:
        if unsupported:
            raise ResearchConfigError("unsupported ResearchSpec fields: %s" % sorted(unsupported))
        pd = require_research_runtime()
        if not isinstance(grid, pd.DataFrame):
            raise ResearchConfigError("grid must be a pandas DataFrame")
        grid_copy = grid.copy(deep=True)
        if (
            not isinstance(grid_copy.index, pd.DatetimeIndex)
            or grid_copy.index.name != "close_time"
        ):
            raise ResearchConfigError("grid index must be a DatetimeIndex named 'close_time'")
        index = _utc_index(grid_copy.index, "grid index", pd)
        if not index.is_unique or not index.is_monotonic_increasing:
            raise ResearchConfigError("grid close_time must be unique and strictly increasing")
        grid_copy.index = index.copy(deep=True)
        if "open_time" not in grid_copy.columns:
            raise ResearchConfigError("grid requires an open_time column")
        open_times = pd.DatetimeIndex(pd.to_datetime(grid_copy["open_time"], errors="coerce"))
        if open_times.isna().any() or open_times.tz is None:
            raise ResearchConfigError("grid open_time values must be timezone-aware UTC datetimes")
        open_times_utc = _utc_index(open_times, "grid open_time", pd)
        if any(open_time > close_time for open_time, close_time in zip(open_times_utc, index)):
            raise ResearchConfigError("grid open_time must not follow its close_time")
        grid_copy["open_time"] = open_times_utc

        start_utc = _timestamp(start, "start", pd)
        end_utc = _timestamp(end, "end", pd)
        if start_utc > end_utc:
            raise ResearchConfigError("start must not follow end")
        if start_utc not in index or end_utc not in index:
            raise ResearchConfigError("start and end must be exact grid close_time endpoints")

        if not isinstance(targets, (tuple, list)) or not targets:
            raise ResearchConfigError("targets must be a non-empty tuple/list of asset names")
        normalized_targets = tuple(_nonempty_string(value, "target") for value in targets)
        if len(set(normalized_targets)) != len(normalized_targets):
            raise ResearchConfigError("target names must be unique")
        source_timezone = _nonempty_string(source_timezone, "source_timezone")
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(source_timezone)
        except (ImportError, KeyError, ValueError) as exc:
            raise ResearchConfigError("source_timezone must be a valid IANA timezone") from exc

        snapshot_id = _nonempty_string(snapshot_id, "snapshot_id")
        price_basis = _nonempty_string(price_basis, "price_basis")
        if price_basis.strip().lower() in {"default", "unknown", "unspecified"}:
            raise ResearchConfigError("price_basis must describe an explicit price convention")
        calendar_id = _nonempty_string(calendar_id, "calendar_id")
        frequency = _nonempty_string(frequency, "frequency")
        if feed_time_kind != "close_time":
            raise ResearchConfigError("feed_time_kind currently supports only 'close_time'")

        if groups is None:
            normalized_groups = dict.fromkeys(normalized_targets, "default")
        elif isinstance(groups, Mapping):
            if set(groups) != set(normalized_targets):
                raise ResearchConfigError("groups must cover exactly all target assets")
            normalized_groups = {
                asset: _nonempty_string(groups[asset], "group") for asset in normalized_targets
            }
        else:
            raise ResearchConfigError("groups must be an asset-to-group mapping")

        study_index = index[(index >= start_utc) & (index <= end_utc)]
        study_keys = pd.MultiIndex.from_product(
            [study_index, normalized_targets], names=("time", "asset")
        )
        universe_defaulted = universe is None
        normalized_universe = _normalize_bool_index(
            universe,
            study_keys,
            pd=pd,
            field_name="universe",
        )

        from ..utils.dateintern import date2num

        calculation_index = grid_copy.index[grid_copy.index <= end_utc]
        calculation_datetime_nums = tuple(
            date2num(value.to_pydatetime()) for value in calculation_index
        )
        calculation_datetime_index_signature = _datetime_index_signature(calculation_index)

        object.__setattr__(self, "_grid", grid_copy)
        object.__setattr__(self, "_grid_sha256", _grid_sha256(grid_copy))
        object.__setattr__(self, "_feed_datetime_nums", calculation_datetime_nums)
        object.__setattr__(
            self, "_feed_datetime_index_signature", calculation_datetime_index_signature
        )
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
        object.__setattr__(self, "universe_defaulted", universe_defaulted)

    @property
    def grid(self) -> Any:
        return _copy_frame_with_owned_index(self._grid)

    @property
    def groups(self) -> Mapping[str, str]:
        return self._groups

    @property
    def universe(self) -> Any:
        return self._universe.copy(deep=True)

    @property
    def calculation_grid(self) -> Any:
        """Full warm-up through research-end grid, excluding the label tail."""
        return _copy_frame_with_owned_index(self._grid.loc[self._grid.index <= self.end])

    @property
    def grid_sha256(self) -> str:
        return self._grid_sha256


def _normalize_bool_index(
    value: Any,
    expected_index: Any,
    *,
    pd: Any,
    field_name: str,
) -> Any:
    if value is None:
        return pd.Series(True, index=expected_index, dtype=bool, name=field_name)
    if not isinstance(value, pd.Series):
        raise ResearchConfigError(
            "%s must be a boolean Series indexed by (time, asset)" % field_name
        )
    result = value.copy(deep=True)
    if not isinstance(result.index, pd.MultiIndex) or tuple(result.index.names) != (
        "time",
        "asset",
    ):
        raise ResearchConfigError("%s index must be named (time, asset)" % field_name)
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


__all__ = (
    "FactorHistoryContract",
    "FactorSpec",
    "ResearchSpec",
    "normalize_factor_specs",
    "require_research_runtime",
    "thaw",
)
