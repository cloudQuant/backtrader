"""Immutable, replayable snapshots of native factor collection output.

This module deliberately has no import-time pandas or fincore dependency. The
tabular dependency and the supported research Python version are checked only
when a dataset is constructed, loaded, or evaluated.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

from ..errors import DatasetError
from .specs import require_research_runtime

_AVAILABILITY_COLUMNS = ("ready", "valid", "reason")
_CLASSIFICATION_LEVELS = frozenset(("sector", "industry", "subindustry"))
_AVAILABILITY_REASONS = frozenset(
    (
        "READY",
        "NOT_READY",
        "NO_CURRENT_BAR",
        "NONFINITE_INPUT",
        "MISSING_FIELD",
        "NOT_YET_AVAILABLE",
        "UNKNOWN_CLASSIFICATION",
        "FORMULA_INELIGIBLE",
        "INCOMPLETE_WINDOW",
        "DOMAIN_ERROR",
    )
)
_UNREADY_OUTPUT_REASONS = frozenset(
    (
        "NOT_READY",
        "NO_CURRENT_BAR",
        "MISSING_FIELD",
        "NOT_YET_AVAILABLE",
        "UNKNOWN_CLASSIFICATION",
        "FORMULA_INELIGIBLE",
        "INCOMPLETE_WINDOW",
    )
)


def _dataset_error(
    message: str, code: str = "INVALID_DATASET", report: Optional[Mapping] = None
) -> DatasetError:
    return DatasetError(message, code=code, report=report)


def _frame_copy(value: Any, name: str, pandas: Any) -> Any:
    if not isinstance(value, pandas.DataFrame):
        raise _dataset_error("%s must be a pandas DataFrame" % name)
    result = value.copy(deep=True)
    result.attrs = copy.deepcopy(value.attrs)
    # pandas' deep copy does not recursively copy Python objects stored in an
    # object-dtype cell. Snapshot those JSON-like containers explicitly so a
    # caller cannot mutate sealed provenance through an aliased dict/list.
    for column in result.columns:
        if pandas.api.types.is_object_dtype(result[column].dtype):
            result[column] = result[column].map(_copy_cell_container)
    return result


def _copy_cell_container(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _copy_cell_container(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_cell_container(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_cell_container(item) for item in value)
    if isinstance(value, set):
        return {_copy_cell_container(item) for item in value}
    return value


def _utc_timestamp(value: Any, name: str, pandas: Any) -> Any:
    try:
        result = pandas.Timestamp(value)
    except Exception as exc:
        raise _dataset_error("%s must be a timezone-aware timestamp" % name) from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise _dataset_error("%s must be timezone-aware" % name)
    return result.tz_convert("UTC")


def _utc_datetime_index(values: Any, name: str, pandas: Any) -> Any:
    try:
        index = pandas.DatetimeIndex(values)
    except Exception as exc:
        raise _dataset_error("%s must be a UTC DatetimeIndex" % name) from exc
    if index.tz is None:
        raise _dataset_error("%s must be timezone-aware" % name)
    return index.tz_convert("UTC")


def _normalise_multiindex(frame: Any, names: Tuple[str, ...], label: str, pandas: Any) -> Any:
    if not isinstance(frame.index, pandas.MultiIndex) or frame.index.nlevels != len(names):
        raise _dataset_error("%s index must have levels %s" % (label, names))
    current_names = tuple(frame.index.names)
    if current_names != names:
        # evaluation_time is the older descriptive name used by the DS45-03
        # table; normalize it to the fincore/public ``time`` axis.
        if current_names == ("evaluation_time",) + names[1:]:
            frame.index = frame.index.set_names(names)
        else:
            raise _dataset_error("%s index names must be %s" % (label, names))
    arrays = [
        frame.index.get_level_values(0),
        *[frame.index.get_level_values(i) for i in range(1, len(names))],
    ]
    arrays[0] = _utc_datetime_index(arrays[0], "%s time index" % label, pandas)
    if arrays[0].hasnans:
        raise _dataset_error("%s time index contains a missing timestamp" % label)
    for axis_name, values in zip(names[1:], arrays[1:]):
        if axis_name in ("asset", "factor") and any(
            not isinstance(value, str) or not value for value in values
        ):
            raise _dataset_error("%s %s axis values must be non-empty strings" % (label, axis_name))
    try:
        frame.index = pandas.MultiIndex.from_arrays(arrays, names=names)
    except (TypeError, ValueError) as exc:
        raise _dataset_error("%s index cannot be normalized" % label) from exc
    if frame.index.has_duplicates:
        raise _dataset_error("%s index contains duplicate keys" % label)
    return frame


def _spec_value(spec: Any, name: str, default: Any = None) -> Any:
    if spec is None:
        return default
    if isinstance(spec, Mapping):
        return spec.get(name, default)
    return getattr(spec, name, default)


def _metadata_value(value: Any, pandas: Any) -> Any:
    """Convert configuration metadata to a finite JSON-only value tree."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise _dataset_error("dataset provenance cannot contain non-finite numbers")
        return value
    if isinstance(value, (list, tuple)):
        return [_metadata_value(item, pandas) for item in value]
    if isinstance(value, Mapping):
        output = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise _dataset_error("dataset provenance keys must be non-empty strings")
            output[key] = _metadata_value(item, pandas)
        return output
    if isinstance(value, (pandas.Timestamp,)):
        if value.tzinfo is None:
            raise _dataset_error("dataset provenance timestamps must be timezone-aware")
        return value.tz_convert("UTC").isoformat().replace("+00:00", "Z")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise _dataset_error("dataset provenance timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    # numpy scalar values are common in user-supplied provenance. Convert only
    # scalar JSON-compatible values; never serialize arbitrary Python objects.
    item = getattr(value, "item", None)
    if callable(item):
        converted = item()
        if converted is not value:
            return _metadata_value(converted, pandas)
    raise _dataset_error("dataset provenance contains an unsupported value")


class ResearchDataset(object):
    """A validated immutable copy of factor values and their source context.

    ``grid`` retains the full warm-up, research, and label-tail interval.
    ``raw_factors`` and ``availability`` are stored only for the declared
    research interval. All public pandas properties return defensive copies.
    """

    schema_version = 1
    __slots__ = (
        "_grid",
        "_start",
        "_end",
        "_targets",
        "_factor_names",
        "_raw_factors",
        "_availability",
        "_prices",
        "_groups",
        "_universe",
        "_formula_universe",
        "_formula_inputs",
        "_classifications",
        "_precomputed_returns",
        "_metadata",
        "_dataset_id",
        "_sealed",
    )

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("ResearchDataset snapshots are immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("ResearchDataset snapshots are immutable")
        object.__delattr__(self, name)

    def __init__(
        self,
        grid: Any,
        raw_factors: Any,
        availability: Any,
        *,
        research_spec: Any = None,
        prices: Optional[Mapping] = None,
        universe: Any = None,
        groups: Optional[Mapping] = None,
        formula_universe: Any = None,
        formula_inputs: Optional[Mapping] = None,
        classifications: Optional[Mapping] = None,
        precomputed_returns: Any = None,
        provenance: Optional[Mapping] = None,
        start: Any = None,
        end: Any = None,
        targets: Optional[Tuple[str, ...]] = None,
        metadata: Optional[Mapping] = None,
    ) -> None:
        pd = require_research_runtime()
        self._grid = self._validate_grid(grid, pd)

        if research_spec is not None:
            start = _spec_value(research_spec, "start", start)
            end = _spec_value(research_spec, "end", end)
            targets = _spec_value(research_spec, "targets", targets)
            if universe is None:
                universe = _spec_value(research_spec, "universe", None)
            if groups is None:
                groups = _spec_value(research_spec, "groups", None)
            if formula_universe is None:
                formula_universe = _spec_value(research_spec, "formula_universe", None)
            if formula_inputs is None:
                formula_inputs = _spec_value(research_spec, "formula_fields", None)
            if classifications is None:
                classifications = _spec_value(research_spec, "classifications", None)

        raw = _frame_copy(raw_factors, "raw_factors", pd)
        raw = _normalise_multiindex(raw, ("time", "asset"), "raw_factors", pd)
        if len(raw.columns) == 0:
            raise _dataset_error("raw_factors must contain at least one factor")
        if any(not isinstance(name, str) or not name for name in raw.columns):
            raise _dataset_error("factor columns must be non-empty strings")
        if raw.columns.has_duplicates:
            raise _dataset_error("raw_factors contains duplicate factor names")
        for name in raw.columns:
            try:
                raw[name] = pd.to_numeric(raw[name], errors="raise").astype("float64")
            except (TypeError, ValueError, OverflowError) as exc:
                raise _dataset_error("raw factor %s must be numeric" % name) from exc
            values = raw[name]
            if bool(
                values.map(lambda value: value == float("inf") or value == float("-inf")).any()
            ):
                raise _dataset_error("raw factors cannot contain positive or negative infinity")

        if targets is None:
            if not isinstance(raw.index, pd.MultiIndex):
                raise _dataset_error("targets are required when raw_factors has no usable index")
            targets = tuple(sorted(set(raw.index.get_level_values("asset"))))
        if isinstance(targets, (str, bytes)):
            raise _dataset_error("targets must be a non-empty sequence of asset names")
        try:
            targets = tuple(targets)
        except TypeError as exc:
            raise _dataset_error("targets must be a non-empty sequence of asset names") from exc
        if not targets or any(not isinstance(asset, str) or not asset for asset in targets):
            raise _dataset_error("targets must be non-empty strings")
        if len(set(targets)) != len(targets):
            raise _dataset_error("targets must be unique")
        targets = tuple(sorted(targets))
        raw_assets = set(raw.index.get_level_values("asset"))
        if not raw_assets.issubset(set(targets)):
            raise _dataset_error("raw_factors contains an undeclared asset")

        grid_index = self._grid.index
        if start is None:
            start = raw.index.get_level_values("time").min()
        if end is None:
            end = raw.index.get_level_values("time").max()
        start = _utc_timestamp(start, "start", pd)
        end = _utc_timestamp(end, "end", pd)
        if start > end or start not in grid_index or end not in grid_index:
            raise _dataset_error("start and end must be ordered grid close_time endpoints")
        self._start = start
        self._end = end
        self._targets = targets
        self._factor_names = tuple(sorted(raw.columns))

        if not raw.index.get_level_values("time").isin(grid_index).all():
            raise _dataset_error("raw_factors contains a time outside the declared grid")
        research_times = grid_index[(grid_index >= start) & (grid_index <= end)]
        if not len(research_times):
            raise _dataset_error("research interval contains no grid points")
        expected_panel_index = pd.MultiIndex.from_product(
            [research_times, targets], names=["time", "asset"]
        )
        research_raw = raw.loc[raw.index.get_level_values("time").isin(research_times)]
        if not set(research_raw.index.get_level_values("asset")).issubset(set(targets)):
            raise _dataset_error("raw_factors contains an undeclared target")
        research_raw = research_raw.reindex(expected_panel_index)
        research_raw = research_raw.reindex(columns=self._factor_names)
        self._raw_factors = research_raw.astype("float64")

        self._availability = self._validate_availability(
            availability, expected_panel_index, self._factor_names, self._raw_factors, pd
        )
        self._prices = self._validate_prices(prices, targets, self._grid, pd)
        self._groups = self._validate_groups(groups, targets)
        self._universe = self._validate_universe(universe, expected_panel_index, pd)
        self._formula_universe = self._validate_formula_universe(
            formula_universe, grid_index, targets, start, end, pd
        )
        self._formula_inputs = self._validate_named_tables(
            formula_inputs or {}, "formula_inputs", pd
        )
        self._classifications = self._validate_named_tables(
            classifications or {}, "classifications", pd
        )
        self._precomputed_returns = self._validate_precomputed_returns(
            precomputed_returns, research_times, targets, pd
        )

        spec_metadata = self._research_metadata(research_spec, start, end, targets, pd)
        if metadata is not None and not isinstance(metadata, Mapping):
            raise _dataset_error("dataset metadata must be a JSON mapping")
        if provenance is not None and not isinstance(provenance, Mapping):
            raise _dataset_error("dataset provenance must be a JSON mapping")
        user_metadata = _metadata_value(metadata or {}, pd)
        source_provenance = _metadata_value(provenance or {}, pd)
        self._metadata = {
            "research": spec_metadata,
            "provenance": source_provenance,
            "metadata": user_metadata,
        }
        from .storage import compute_dataset_id

        self._dataset_id = compute_dataset_id(self)
        self._sealed = True

    @classmethod
    def from_collection(
        cls,
        *,
        research: Any,
        raw_factors: Any,
        availability: Any,
        prices: Optional[Mapping] = None,
        formula_inputs: Optional[Mapping] = None,
        classifications: Optional[Mapping] = None,
        precomputed_returns: Any = None,
        provenance: Optional[Mapping] = None,
    ) -> "ResearchDataset":
        """Seal a completed native collector result with its ResearchSpec."""
        if research is None:
            raise _dataset_error("completed collection requires a ResearchSpec")
        return cls(
            _spec_value(research, "grid"),
            raw_factors,
            availability,
            research_spec=research,
            prices=prices,
            formula_inputs=formula_inputs,
            classifications=classifications,
            precomputed_returns=precomputed_returns,
            provenance=provenance,
        )

    @staticmethod
    def _validate_grid(grid: Any, pd: Any) -> Any:
        result = _frame_copy(grid, "grid", pd)
        if not isinstance(result.index, pd.DatetimeIndex) or result.index.name != "close_time":
            raise _dataset_error("grid index must be a DatetimeIndex named close_time")
        close_time = _utc_datetime_index(result.index, "grid close_time", pd)
        if (
            close_time.hasnans
            or close_time.has_duplicates
            or not close_time.is_monotonic_increasing
        ):
            raise _dataset_error("grid close_time must be unique and strictly increasing")
        result.index = close_time.rename("close_time")
        if "open_time" not in result.columns:
            raise _dataset_error("grid must contain open_time")
        open_time = _utc_datetime_index(result["open_time"], "grid open_time", pd)
        if open_time.hasnans:
            raise _dataset_error("grid open_time must be timezone-aware")
        if len(open_time) != len(close_time) or bool((open_time >= close_time).any()):
            raise _dataset_error("each grid open_time must precede its close_time")
        if len(close_time) > 1 and bool((open_time[1:] < close_time[:-1]).any()):
            raise _dataset_error("grid bars must not overlap")
        result["open_time"] = open_time
        return result

    @staticmethod
    def _validate_availability(
        availability: Any,
        expected_panel_index: Any,
        factors: Tuple[str, ...],
        raw_factors: Any,
        pd: Any,
    ) -> Any:
        frame = _frame_copy(availability, "availability", pd)
        frame = _normalise_multiindex(frame, ("time", "asset", "factor"), "availability", pd)
        if "ready" not in frame.columns and "ready_state" in frame.columns:
            state = frame["ready_state"]
            frame["ready"] = state.astype(str).eq("READY")
        required_columns = _AVAILABILITY_COLUMNS + ("available_at", "input_times")
        missing = [column for column in required_columns if column not in frame.columns]
        if missing:
            raise _dataset_error("availability is missing required columns: %s" % missing)
        factor_values = set(frame.index.get_level_values("factor"))
        if not factor_values.issubset(set(factors)):
            raise _dataset_error("availability contains an undeclared factor")
        expected_index = pd.MultiIndex.from_product(
            [
                expected_panel_index.get_level_values("time").unique(),
                expected_panel_index.get_level_values("asset").unique(),
                factors,
            ],
            names=["time", "asset", "factor"],
        )
        # Do not discard collector rows outside the research interval. They
        # may indicate a bad slice or a misaligned clock and must be visible.
        outside_keys = frame.index.difference(expected_index)
        if len(outside_keys):
            raise _dataset_error(
                "availability contains keys outside the research time/asset/factor grid",
                report={"outside_count": int(len(outside_keys))},
            )
        missing_keys = expected_index.difference(frame.index)
        if len(missing_keys):
            raise _dataset_error(
                "availability must describe every research time/asset/factor cell",
                report={"missing_count": int(len(missing_keys))},
            )
        frame = frame.reindex(expected_index)
        for column in ("ready", "valid"):
            if frame[column].isna().any() or not pd.api.types.is_bool_dtype(frame[column].dtype):
                raise _dataset_error("availability %s values must be booleans" % column)
            frame[column] = frame[column].astype(bool)
        if (
            frame["reason"].isna().any()
            or not frame["reason"].map(lambda value: isinstance(value, str) and bool(value)).all()
        ):
            raise _dataset_error("availability reasons must be non-empty strings")
        unknown_reasons = set(frame["reason"]) - _AVAILABILITY_REASONS
        if unknown_reasons:
            raise _dataset_error(
                "availability contains unknown reason codes",
                report={"unknown_reasons": tuple(sorted(unknown_reasons))},
            )
        normalized_available_at = []
        normalized_input_times = []
        for (time, asset, factor), row in frame.iterrows():
            value = raw_factors.at[(time, asset), factor]
            is_finite = not pd.isna(value)
            reason = row["reason"]
            ready = bool(row["ready"])
            valid = bool(row["valid"])
            if valid and not ready:
                raise _dataset_error("valid availability cells must also be ready")
            if row["valid"] and not is_finite:
                raise _dataset_error("availability cannot mark a missing factor value valid")
            if not row["valid"] and is_finite:
                raise _dataset_error("invalid factor cells must not retain a numeric value")
            if reason == "READY" and not (ready and valid and is_finite):
                raise _dataset_error("READY requires ready, valid, finite factor output")
            if reason == "NONFINITE_INPUT" and not (ready and not valid and not is_finite):
                raise _dataset_error("NONFINITE_INPUT requires ready output with an explicit NaN")
            if reason in _UNREADY_OUTPUT_REASONS and (ready or valid):
                raise _dataset_error("%s requires an unready, invalid output" % reason)
            if reason == "DOMAIN_ERROR" and (not ready or valid or is_finite):
                raise _dataset_error("DOMAIN_ERROR requires a ready but missing output")
            available_at = row.get("available_at")
            if available_at is not None and not pd.isna(available_at):
                stamp = _utc_timestamp(available_at, "availability.available_at", pd)
                # This column timestamps the factor output itself and must be
                # on or before the evaluation grid point. A known future PIT
                # source publication is retained separately under input_times.
                if stamp > time:
                    raise _dataset_error(
                        "factor input availability cannot be later than its grid time"
                    )
                normalized_available_at.append(stamp)
            elif reason in ("READY", "NONFINITE_INPUT", "DOMAIN_ERROR"):
                raise _dataset_error("computed factor cells require an available_at timestamp")
            else:
                normalized_available_at.append(pd.NaT)
            input_times = row.get("input_times")
            if not isinstance(input_times, Mapping) or not input_times:
                raise _dataset_error(
                    "availability input_times must map each input alias to its actual time"
                )
            normalized_times: Dict[str, Any] = {}
            has_missing_input_time = False
            for alias, actual_time in input_times.items():
                if not isinstance(alias, str) or not alias:
                    raise _dataset_error(
                        "availability input time aliases must be non-empty strings"
                    )
                if actual_time is None or actual_time is pd.NaT or actual_time is pd.NA:
                    has_missing_input_time = True
                    normalized_times[alias] = None
                    continue
                values = actual_time if isinstance(actual_time, (tuple, list)) else (actual_time,)
                if not values:
                    raise _dataset_error("availability input time sequences cannot be empty")
                normalized_values: list[Optional[str]] = []
                for actual_stamp in values:
                    if actual_stamp is None or actual_stamp is pd.NaT or actual_stamp is pd.NA:
                        has_missing_input_time = True
                        normalized_values.append(None)
                        continue
                    stamp = _utc_timestamp(actual_stamp, "availability.input_times.%s" % alias, pd)
                    # A late source timestamp is evidence for this reason
                    # only; computed/usable outputs cannot depend on it.
                    if stamp > time and reason != "NOT_YET_AVAILABLE":
                        raise _dataset_error(
                            "factor input times cannot be later than their grid time"
                        )
                    normalized_values.append(stamp.isoformat().replace("+00:00", "Z"))
                normalized_times[alias] = (
                    normalized_values
                    if isinstance(actual_time, (tuple, list))
                    else normalized_values[0]
                )
            if has_missing_input_time and (ready or valid or reason not in _UNREADY_OUTPUT_REASONS):
                raise _dataset_error(
                    "missing input time positions require an unready invalid availability reason"
                )
            if reason in ("READY", "NONFINITE_INPUT") and (
                not normalized_times or has_missing_input_time
            ):
                raise _dataset_error(
                    "%s requires a known actual time for every used input" % reason
                )
            normalized_input_times.append(normalized_times)
        frame["available_at"] = pd.to_datetime(normalized_available_at, utc=True)
        frame["input_times"] = normalized_input_times
        frame = frame.reindex(columns=sorted(frame.columns))
        return frame

    @staticmethod
    def _validate_prices(
        prices: Optional[Mapping], targets: Tuple[str, ...], grid: Any, pd: Any
    ) -> Dict[str, Any]:
        if prices is None:
            return {}
        if not isinstance(prices, Mapping):
            raise _dataset_error("prices must map open/close to DataFrames")
        if set(prices) not in (set(), {"open", "close"}):
            raise _dataset_error("prices must contain both open and close matrices, or neither")
        unknown = set(prices) - {"open", "close"}
        if unknown:
            raise _dataset_error("prices may contain only open and close matrices")
        output = {}
        for name, value in prices.items():
            frame = _frame_copy(value, "prices.%s" % name, pd)
            if not isinstance(frame.index, pd.DatetimeIndex):
                raise _dataset_error("prices.%s must use a DatetimeIndex" % name)
            frame.index = _utc_datetime_index(frame.index, "prices.%s index" % name, pd)
            frame.index.name = "time"
            if frame.index.has_duplicates:
                raise _dataset_error("prices.%s index contains duplicates" % name)
            if not frame.columns.is_unique or any(
                not isinstance(column, str) or not column for column in frame.columns
            ):
                raise _dataset_error(
                    "prices.%s columns must be unique non-empty asset names" % name
                )
            if not frame.index.isin(grid.index).all():
                raise _dataset_error("prices.%s contains a time outside grid" % name)
            if set(frame.columns) - set(targets):
                raise _dataset_error("prices.%s contains an undeclared asset" % name)
            try:
                frame = frame.reindex(index=grid.index, columns=targets).astype("float64")
            except (TypeError, ValueError, OverflowError) as exc:
                raise _dataset_error("prices.%s must contain numeric values" % name) from exc
            if bool(
                frame.apply(
                    lambda column: column.map(
                        lambda item: item == float("inf") or item == float("-inf")
                    ).any()
                ).any()
            ):
                raise _dataset_error("prices cannot contain positive or negative infinity")
            output[name] = frame
        return output

    @staticmethod
    def _validate_groups(groups: Optional[Mapping], targets: Tuple[str, ...]) -> Dict[str, str]:
        if groups is None:
            return dict.fromkeys(targets, "default")
        if not isinstance(groups, Mapping) or set(groups) != set(targets):
            raise _dataset_error("groups must map every target to exactly one research group")
        output = {}
        for asset in targets:
            value = groups[asset]
            if not isinstance(value, str) or not value:
                raise _dataset_error("group labels must be non-empty strings")
            output[asset] = value
        return output

    @staticmethod
    def _validate_universe(universe: Any, expected_index: Any, pd: Any) -> Any:
        if universe is None:
            result = pd.Series(True, index=expected_index, name="eligible", dtype=bool)
            return result
        if isinstance(universe, pd.DataFrame):
            if universe.shape[1] != 1:
                raise _dataset_error("universe DataFrame must have one boolean column")
            universe = universe.iloc[:, 0]
        if not isinstance(universe, pd.Series):
            raise _dataset_error("universe must be a bool Series indexed by (time, asset)")
        frame = universe.to_frame("eligible")
        frame = _normalise_multiindex(frame, ("time", "asset"), "universe", pd)
        if set(frame.index) != set(expected_index):
            raise _dataset_error(
                "universe must cover the complete research grid and targets", "UNKNOWN_UNIVERSE"
            )
        values = frame["eligible"]
        if values.isna().any() or not pd.api.types.is_bool_dtype(values.dtype):
            raise DatasetError(
                "universe values must be known booleans",
                code="UNKNOWN_UNIVERSE",
                report={
                    "field": "universe",
                    "unknown_count": int(values.isna().sum()),
                    "invalid_type": not pd.api.types.is_bool_dtype(values.dtype),
                },
            )
        result = values.reindex(expected_index).astype(bool)
        result.name = "eligible"
        return result

    @staticmethod
    def _validate_formula_universe(
        formula_universe: Any,
        grid_index: Any,
        targets: Tuple[str, ...],
        start: Any,
        end: Any,
        pd: Any,
    ) -> Any:
        # Formula membership spans warm-up through research end, unlike the
        # evaluation universe which is bounded by start/end.
        times = grid_index[grid_index <= end]
        expected = pd.MultiIndex.from_product([times, targets], names=["time", "asset"])
        if formula_universe is None:
            return pd.Series(True, index=expected, name="eligible", dtype=bool)
        if isinstance(formula_universe, pd.DataFrame):
            if formula_universe.shape[1] != 1:
                raise _dataset_error("formula_universe DataFrame must have one boolean column")
            formula_universe = formula_universe.iloc[:, 0]
        if not isinstance(formula_universe, pd.Series):
            raise _dataset_error("formula_universe must be a bool Series indexed by (time, asset)")
        frame = formula_universe.to_frame("eligible")
        frame = _normalise_multiindex(frame, ("time", "asset"), "formula_universe", pd)
        outside = frame.index.difference(expected)
        missing = expected.difference(frame.index)
        if len(outside) or len(missing):
            raise DatasetError(
                "formula_universe must cover exactly warm-up through research end",
                code="UNKNOWN_UNIVERSE",
                report={
                    "field": "formula_universe",
                    "missing_count": int(len(missing)),
                    "extra_count": int(len(outside)),
                },
            )
        values = frame["eligible"]
        if values.isna().any() or not pd.api.types.is_bool_dtype(values.dtype):
            raise DatasetError(
                "formula_universe values must be known booleans",
                code="UNKNOWN_UNIVERSE",
                report={
                    "field": "formula_universe",
                    "unknown_count": int(values.isna().sum()),
                    "invalid_type": not pd.api.types.is_bool_dtype(values.dtype),
                },
            )
        result = values.reindex(expected).astype(bool)
        result.name = "eligible"
        return result

    @staticmethod
    def _validate_named_tables(tables: Mapping, label: str, pd: Any) -> Dict[str, Any]:
        if not isinstance(tables, Mapping):
            raise _dataset_error("%s must be a name-to-DataFrame mapping" % label)
        output = {}
        for name, value in tables.items():
            if not isinstance(name, str) or not name:
                raise _dataset_error("%s names must be non-empty strings" % label)
            frame = _frame_copy(value, "%s.%s" % (label, name), pd)
            source_metadata = None
            if label == "formula_inputs":
                attrs = frame.attrs
                if not isinstance(attrs, Mapping) or set(attrs) - {"source_metadata"}:
                    raise DatasetError(
                        "%s.%s has unsupported DataFrame attrs" % (label, name),
                        code="MISSING_INPUT",
                        report={"table": name, "field": "attrs"},
                    )
                if "source_metadata" in attrs:
                    source_metadata = _metadata_value(attrs["source_metadata"], pd)
                    if (
                        not isinstance(source_metadata, dict)
                        or not source_metadata
                        or any(isinstance(item, (dict, list)) for item in source_metadata.values())
                    ):
                        raise DatasetError(
                            "%s.%s source_metadata must be a non-empty flat JSON mapping"
                            % (label, name),
                            code="MISSING_INPUT",
                            report={"table": name, "field": "source_metadata"},
                        )
            if not isinstance(frame.index, pd.MultiIndex) or tuple(frame.index.names) != (
                "time",
                "asset",
            ):
                raise _dataset_error("%s.%s index must be named (time, asset)" % (label, name))
            if frame.index.has_duplicates:
                raise _dataset_error("%s.%s contains duplicate keys" % (label, name))
            if any(not isinstance(column, str) or not column for column in frame.columns):
                raise _dataset_error("%s.%s column names must be non-empty strings" % (label, name))
            if frame.columns.has_duplicates:
                raise _dataset_error("%s.%s contains duplicate columns" % (label, name))
            times = _utc_datetime_index(
                frame.index.get_level_values("time"), "%s.%s time index" % (label, name), pd
            )
            assets = frame.index.get_level_values("asset")
            if any(not isinstance(asset, str) or not asset for asset in assets):
                raise _dataset_error("%s.%s assets must be non-empty strings" % (label, name))
            frame.index = pd.MultiIndex.from_arrays([times, assets], names=("time", "asset"))
            if frame.index.has_duplicates:
                raise _dataset_error("%s.%s contains duplicate UTC-normalized keys" % (label, name))
            if label == "formula_inputs":
                required = {"value", "available_at", "data_version"}
            else:
                required = {
                    "level",
                    "category",
                    "effective_at",
                    "available_at",
                    "taxonomy_version",
                }
            missing = required - set(frame.columns)
            if missing:
                raise DatasetError(
                    "%s.%s is missing required schema columns" % (label, name),
                    code="MISSING_INPUT",
                    report={"table": name, "missing_columns": tuple(sorted(missing))},
                )
            frame = frame.sort_index(kind="mergesort").reindex(columns=sorted(frame.columns))
            for column in ("available_at", "effective_at"):
                if column not in frame.columns:
                    continue
                converted = []
                for index_key, row in frame.iterrows():
                    value = row[column]
                    if value is None or pd.isna(value):
                        if column in required:
                            raise _dataset_error(
                                "%s.%s %s cannot be missing" % (label, name, column)
                            )
                        converted.append(pd.NaT)
                        continue
                    stamp = _utc_timestamp(value, "%s.%s.%s" % (label, name, column), pd)
                    # Source-side PIT tables intentionally retain records that
                    # become available/effective after their source timestamp.
                    # The as-of adapter masks them at evaluation time; do not
                    # rewrite or discard their actual timestamps here.
                    converted.append(stamp)
                frame[column] = pd.to_datetime(converted, utc=True)
            if label == "classifications":
                if (
                    not frame["level"]
                    .map(lambda item: isinstance(item, str) and item in _CLASSIFICATION_LEVELS)
                    .all()
                ):
                    raise DatasetError(
                        "%s.%s level must be sector, industry, or subindustry" % (label, name),
                        code="MISSING_INPUT",
                        report={"table": name, "field": "level"},
                    )
                categories = frame["category"]
                missing_categories = categories.isna()
                invalid_categories = categories.loc[~missing_categories].map(
                    lambda item: not isinstance(item, str) or not item.strip()
                )
                if invalid_categories.any():
                    raise DatasetError(
                        "%s.%s category values must be non-empty strings or missing"
                        % (label, name),
                        code="MISSING_INPUT",
                        report={
                            "table": name,
                            "field": "category",
                            "invalid_count": int(invalid_categories.sum()),
                        },
                    )
            if label == "formula_inputs":
                versions = frame["data_version"]
            else:
                versions = frame["taxonomy_version"]
            if (
                versions.isna().any()
                or not versions.map(lambda item: isinstance(item, str) and bool(item.strip())).all()
            ):
                raise _dataset_error(
                    "%s.%s version metadata must be non-empty strings" % (label, name)
                )
            for column in frame.columns:
                if pd.api.types.is_numeric_dtype(
                    frame[column].dtype
                ) and not pd.api.types.is_bool_dtype(frame[column].dtype):
                    values = pd.to_numeric(frame[column], errors="raise")
                    if bool(
                        values.dropna()
                        .map(lambda item: item == float("inf") or item == float("-inf"))
                        .any()
                    ):
                        raise _dataset_error("%s.%s cannot contain infinity" % (label, name))
            frame.attrs = {}
            if source_metadata is not None:
                frame.attrs["source_metadata"] = copy.deepcopy(source_metadata)
            output[name] = frame
        return output

    @staticmethod
    def _validate_precomputed_returns(
        value: Any, research_times: Any, targets: Tuple[str, ...], pd: Any
    ) -> Any:
        if value is None:
            return None
        frame = _frame_copy(value, "precomputed_returns", pd)
        frame = _normalise_multiindex(
            frame, ("time", "asset", "horizon"), "precomputed_returns", pd
        )
        horizons = frame.index.get_level_values("horizon")
        if (
            not pd.api.types.is_integer_dtype(horizons.dtype)
            or pd.api.types.is_bool_dtype(horizons.dtype)
            or any(int(horizon) <= 0 for horizon in horizons)
        ):
            raise _dataset_error("precomputed return horizons must be positive integers")
        required = ("value", "entry_time", "exit_time", "label_id", "unit", "price_semantics")
        if any(column not in frame.columns for column in required):
            raise _dataset_error("precomputed_returns has an incomplete schema")
        if set(frame.index.get_level_values("asset")) - set(targets):
            raise _dataset_error("precomputed_returns contains an undeclared asset")
        if not frame.index.get_level_values("time").isin(research_times).all():
            raise _dataset_error("precomputed_returns time lies outside the research interval")
        try:
            frame["value"] = pd.to_numeric(frame["value"], errors="raise").astype("float64")
        except (TypeError, ValueError, OverflowError) as exc:
            raise _dataset_error("precomputed return values must be numeric") from exc
        if bool(frame["value"].map(lambda x: x == float("inf") or x == float("-inf")).any()):
            raise _dataset_error("precomputed returns cannot contain infinity")
        for column in ("entry_time", "exit_time"):
            converted = []
            for item in frame[column]:
                converted.append(pd.NaT if pd.isna(item) else _utc_timestamp(item, column, pd))
            frame[column] = pd.to_datetime(converted, utc=True)
        for column in ("label_id", "unit", "price_semantics"):
            if (
                frame[column].isna().any()
                or not frame[column]
                .map(lambda item: isinstance(item, str) and bool(item.strip()))
                .all()
            ):
                raise _dataset_error("precomputed return %s must be non-empty strings" % column)
        finite_values = frame["value"].notna()
        if bool(
            (
                frame.loc[finite_values, "entry_time"].isna()
                | frame.loc[finite_values, "exit_time"].isna()
            ).any()
        ):
            raise _dataset_error("finite precomputed returns require entry and exit times")
        if bool(
            (frame.loc[finite_values, "exit_time"] <= frame.loc[finite_values, "entry_time"]).any()
        ):
            raise _dataset_error("precomputed return exit_time must follow entry_time")
        return frame.sort_index(kind="mergesort").reindex(columns=sorted(frame.columns))

    @staticmethod
    def _research_metadata(
        spec: Any, start: Any, end: Any, targets: Tuple[str, ...], pd: Any
    ) -> Dict[str, Any]:
        fields = (
            "source_timezone",
            "snapshot_id",
            "price_basis",
            "calendar_id",
            "frequency",
            "feed_time_kind",
            "universe_defaulted",
            "formula_universe_defaulted",
        )
        result = {
            "start": _metadata_value(start, pd),
            "end": _metadata_value(end, pd),
            "targets": list(targets),
        }
        for name in fields:
            value = _spec_value(spec, name, None)
            if value is not None:
                result[name] = _metadata_value(value, pd)
        if spec is None:
            for name in ("snapshot_id", "price_basis", "calendar_id", "frequency"):
                result.setdefault(name, "unspecified")
        return result

    @property
    def dataset_id(self) -> str:
        return self._dataset_id

    @property
    def start(self) -> Any:
        return self._start

    @property
    def end(self) -> Any:
        return self._end

    @property
    def targets(self) -> Tuple[str, ...]:
        return self._targets

    @property
    def factor_names(self) -> Tuple[str, ...]:
        return self._factor_names

    @property
    def grid(self) -> Any:
        return self._grid.copy(deep=True)

    @property
    def raw_factors(self) -> Any:
        return self._raw_factors.copy(deep=True)

    @property
    def availability(self) -> Any:
        return _frame_copy(self._availability, "availability", require_research_runtime())

    @property
    def prices(self) -> Dict[str, Any]:
        return {name: frame.copy(deep=True) for name, frame in self._prices.items()}

    @property
    def universe(self) -> Any:
        return self._universe.copy(deep=True)

    @property
    def groups(self) -> Dict[str, str]:
        return dict(self._groups)

    @property
    def formula_universe(self) -> Any:
        return self._formula_universe.copy(deep=True)

    @property
    def formula_inputs(self) -> Dict[str, Any]:
        return {
            name: _frame_copy(frame, "formula_inputs.%s" % name, require_research_runtime())
            for name, frame in self._formula_inputs.items()
        }

    @property
    def classifications(self) -> Dict[str, Any]:
        return {
            name: _frame_copy(frame, "classifications.%s" % name, require_research_runtime())
            for name, frame in self._classifications.items()
        }

    @property
    def precomputed_returns(self) -> Any:
        return (
            None
            if self._precomputed_returns is None
            else _frame_copy(
                self._precomputed_returns, "precomputed_returns", require_research_runtime()
            )
        )

    @property
    def metadata(self) -> Dict[str, Any]:
        return copy.deepcopy(self._metadata)

    def save(self, path: Any) -> Any:
        """Write a deterministic, versioned dataset directory without overwrite."""
        from .storage import save_dataset

        return save_dataset(self, path)

    def evaluate(self, spec: Any = None, **kwargs: Any) -> Any:
        """Evaluate stored values through the public fincore integration adapter."""
        from .fincore_adapter import evaluate_dataset

        return evaluate_dataset(self, spec, **kwargs)


__all__ = ("ResearchDataset",)
