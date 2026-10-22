"""Explicit grid alignment for closed-bar feeds and point-in-time tables."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Optional, cast

from ..errors import ResearchConfigError, DatasetError
from .specs import ResearchSpec, require_research_runtime

_FEED_MARKER = "_factor_research_alignment_v1"


def _utc_datetime_index(values: Any, source_timezone: str, pd: Any, label: str) -> Any:
    try:
        index = pd.DatetimeIndex(pd.to_datetime(values, errors="coerce"))
    except (TypeError, ValueError) as exc:
        raise DatasetError("%s must contain datetime values" % label) from exc
    if index.isna().any():
        raise DatasetError("%s contains invalid or missing timestamps" % label)
    if index.tz is None:
        try:
            index = index.tz_localize(source_timezone, ambiguous="raise", nonexistent="raise")
        except Exception as exc:
            raise DatasetError("%s cannot be localized without ambiguity" % label) from exc
    return index.tz_convert("UTC")


def _utc_series(values: Any, source_timezone: str, index: Any, pd: Any, label: str) -> Any:
    if isinstance(values, pd.Series):
        source = values.copy(deep=True)
        source.index = _utc_datetime_index(source.index, source_timezone, pd, label + " index")
        if not source.index.is_unique:
            raise DatasetError("%s contains duplicate timestamps" % label)
        converted = pd.to_datetime(source, errors="coerce")
        if converted.isna().any():
            raise DatasetError("%s contains missing timestamps" % label)
        if getattr(converted.dt, "tz", None) is None:
            try:
                converted = converted.dt.tz_localize(
                    source_timezone, ambiguous="raise", nonexistent="raise"
                )
            except Exception as exc:
                raise DatasetError(
                    "%s contains ambiguous or nonexistent local timestamps" % label
                ) from exc
        converted = converted.dt.tz_convert("UTC")
        return converted.reindex(index)
    if values is None:
        raise TypeError("values must not be None")
    sequence = list(values)
    if len(sequence) != len(index):
        raise DatasetError("%s length must match the source feed" % label)
    stamps = []
    for value in sequence:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            try:
                stamp = stamp.tz_localize(source_timezone, ambiguous="raise", nonexistent="raise")
            except Exception as exc:
                raise DatasetError(
                    "%s contains ambiguous or nonexistent local timestamps" % label
                ) from exc
        stamps.append(stamp.tz_convert("UTC"))
    return pd.Series(pd.DatetimeIndex(stamps), index=index)


@dataclass(frozen=True, init=False)
class AlignedBars:
    """A full-grid PandasData feed plus immutable alignment diagnostics."""

    asset: str
    feed: Any = field(repr=False, compare=False)
    _frame: Any = field(repr=False, compare=False)
    _present: Any = field(repr=False, compare=False)
    _available_at: Any = field(repr=False, compare=False)
    grid_sha256: str
    data_version: Optional[str]

    def __init__(
        self,
        *,
        asset: str,
        feed: Any,
        frame: Any,
        present: Any,
        available_at: Any,
        grid_sha256: str,
        data_version: Optional[str],
    ) -> None:
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "feed", feed)
        object.__setattr__(self, "_frame", frame.copy(deep=True))
        object.__setattr__(self, "_present", present.copy(deep=True))
        object.__setattr__(self, "_available_at", available_at.copy(deep=True))
        object.__setattr__(self, "grid_sha256", grid_sha256)
        object.__setattr__(self, "data_version", data_version)

    @property
    def frame(self) -> Any:
        return self._frame.copy(deep=True)

    @property
    def present(self) -> Any:
        return self._present.copy(deep=True)

    @property
    def available_at(self) -> Any:
        return self._available_at.copy(deep=True)


def prealign_bars(
    frame: Any,
    research: ResearchSpec,
    asset: str,
    *,
    available_at: Any = None,
    data_version: Optional[str] = None,
) -> AlignedBars:
    """Align a local closed-bar DataFrame to the caller's complete UTC grid.

    Missing rows remain NaN and are marked ``present=False``.  No feed dates
    are intersected, no market value is forward-filled, and a bar unavailable
    at its close time is masked before Backtrader can consume it.
    """
    pd = require_research_runtime()
    if not isinstance(research, ResearchSpec):
        raise ResearchConfigError("research must be a ResearchSpec")
    if not isinstance(frame, pd.DataFrame):
        raise DatasetError("bar input must be a pandas DataFrame")
    if not isinstance(asset, str) or not asset:
        raise ResearchConfigError("asset must be a non-empty feed name")
    if not frame.columns.is_unique:
        raise DatasetError("bar input contains duplicate columns")
    if not frame.index.is_unique:
        raise DatasetError("bar input contains duplicate timestamps")

    source = frame.copy(deep=True)
    source.index = _utc_datetime_index(
        source.index, research.source_timezone, pd, "bar input index"
    )
    source.index.name = "close_time"
    if not source.index.is_monotonic_increasing:
        raise DatasetError("bar input timestamps must be strictly increasing")
    grid = research.grid
    grid_index = grid.index
    outside = source.index.difference(grid_index)
    if len(outside):
        raise DatasetError(
            "bar input contains timestamps outside the declared grid",
            code="INVALID_DATASET",
            report={"asset": asset, "outside_count": int(len(outside))},
        )

    if available_at is None:
        source_available = pd.Series(source.index, index=source.index, name="available_at")
    else:
        source_available = _utc_series(
            available_at, research.source_timezone, source.index, pd, "available_at"
        )
        source_available.index.name = "close_time"
    if source_available.isna().any():
        raise DatasetError(
            "present bars require an available_at timestamp",
            code="MISSING_INPUT",
            report={"asset": asset, "missing_available_at": int(source_available.isna().sum())},
        )

    source_present = pd.Series(True, index=source.index, dtype=bool, name="present")
    full_frame = source.reindex(grid_index).copy(deep=True)
    full_frame.attrs = deepcopy(source.attrs)
    aligned = source.reindex(grid_index).copy(deep=True)
    present = source_present.reindex(grid_index, fill_value=False).astype(bool)
    available = source_available.reindex(grid_index)
    # A row whose source says it is not yet known must not leak into a current
    # factor calculation. Keep the source-presence/availability facts intact.
    future_available = present & (available > grid_index)
    if bool(future_available.any()):
        aligned.loc[future_available, :] = float("nan")
    available.index = grid_index
    present.index = grid_index
    available.name = "available_at"
    present.name = "present"

    if data_version is not None and (not isinstance(data_version, str) or not data_version.strip()):
        raise ResearchConfigError("data_version must be None or a non-empty string")

    calculation_mask = grid_index <= research.end
    calculation_aligned = aligned.loc[calculation_mask].copy(deep=True)
    calculation_present = present.loc[calculation_mask].copy(deep=True)
    calculation_available = available.loc[calculation_mask].copy(deep=True)
    full_prices = {}
    for price_name in ("open", "close"):
        if price_name in aligned.columns:
            values = []
            for value in aligned[price_name].to_numpy():
                try:
                    numeric = float(value)
                except (TypeError, ValueError, OverflowError):
                    numeric = float("nan")
                values.append(
                    numeric if numeric == numeric and abs(numeric) != float("inf") else float("nan")
                )
            full_prices[price_name] = tuple(values)

    try:
        from ..feeds.pandafeed import PandasData
    except ImportError as exc:
        raise DatasetError("PandasData feed implementation is unavailable") from exc
    # Formula feeds stop at the research end. The full aligned frame remains
    # available on AlignedBars for post-end label prices.
    feed = cast(Any, PandasData)(dataname=calculation_aligned)
    metadata = {
        "version": 1,
        "asset": asset,
        "grid_sha256": research.grid_sha256,
        "present": tuple(bool(value) for value in calculation_present.to_numpy()),
        "available_at": tuple(
            None if pd.isna(value) else value.to_pydatetime()
            for value in calculation_available.to_numpy()
        ),
        "full_frame": full_frame,
        "full_present": tuple(bool(value) for value in present.to_numpy()),
        "full_available_at": tuple(
            None if pd.isna(value) else value.to_pydatetime() for value in available.to_numpy()
        ),
        "full_prices": MappingProxyType(full_prices),
        "full_grid": tuple(value.to_pydatetime() for value in grid_index),
        "data_version": data_version,
        "feed_time_kind": research.feed_time_kind,
    }
    setattr(feed, _FEED_MARKER, MappingProxyType(metadata))
    return AlignedBars(
        asset=asset,
        feed=feed,
        frame=aligned,
        present=present,
        available_at=available,
        grid_sha256=research.grid_sha256,
        data_version=data_version,
    )


@dataclass(frozen=True, init=False)
class AlignedPITInput:
    """Point-in-time as-of view for one external field or classification."""

    name: str
    _values: Any = field(repr=False, compare=False)
    _present: Any = field(repr=False, compare=False)
    _available_at: Any = field(repr=False, compare=False)
    _reason: Any = field(repr=False, compare=False)
    classification: bool

    def __init__(
        self,
        *,
        name: str,
        values: Any,
        present: Any,
        available_at: Any,
        reason: Any,
        classification: bool,
    ) -> None:
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "_values", values.copy(deep=True))
        object.__setattr__(self, "_present", present.copy(deep=True))
        object.__setattr__(self, "_available_at", available_at.copy(deep=True))
        object.__setattr__(self, "_reason", reason.copy(deep=True))
        object.__setattr__(self, "classification", classification)

    @property
    def values(self) -> Any:
        return self._values.copy(deep=True)

    @property
    def present(self) -> Any:
        return self._present.copy(deep=True)

    @property
    def available_at(self) -> Any:
        return self._available_at.copy(deep=True)

    @property
    def reason(self) -> Any:
        return self._reason.copy(deep=True)

    def value_at(self, time: Any, asset: str) -> Any:
        key = (time, asset)
        return self._values.loc[key]


def prealign_pit_table(
    table: Any,
    research: ResearchSpec,
    name: str,
    *,
    classification: bool = False,
) -> AlignedPITInput:
    """Build an as-of `(time, asset)` view without exposing future revisions.

    The latest logical source timestamp effective and available at the queried
    grid point is selected.  A known-but-late row is represented as present
    with its future ``available_at`` and a missing value/reason.
    """
    pd = require_research_runtime()
    if not isinstance(research, ResearchSpec):
        raise ResearchConfigError("research must be a ResearchSpec")
    if not isinstance(table, pd.DataFrame):
        raise DatasetError("PIT table must be a pandas DataFrame")
    if not isinstance(table.index, pd.MultiIndex) or tuple(table.index.names) != (
        "time",
        "asset",
    ):
        raise DatasetError("PIT table index must be named (time, asset)")
    if not table.index.is_unique:
        raise DatasetError("PIT table contains duplicate source keys")
    value_column = "category" if classification else "value"
    required = {value_column, "available_at"}
    if classification:
        required.update({"effective_at", "level", "taxonomy_version"})
    missing_columns = required - set(table.columns)
    if missing_columns:
        raise DatasetError(
            "PIT table is missing required columns",
            code="MISSING_INPUT",
            report={"table": name, "missing_columns": tuple(sorted(missing_columns))},
        )

    source = table.copy(deep=True)
    times = _utc_datetime_index(
        source.index.get_level_values("time"), research.source_timezone, pd, name + " time"
    )
    source.index = pd.MultiIndex.from_arrays(
        [times, source.index.get_level_values("asset")], names=("time", "asset")
    )
    available = _utc_datetime_index(
        source["available_at"], research.source_timezone, pd, name + " available_at"
    )
    source["available_at"] = available
    if classification:
        effective = _utc_datetime_index(
            source["effective_at"], research.source_timezone, pd, name + " effective_at"
        )
        source["effective_at"] = effective

    all_times = research.calculation_grid.index
    keys = pd.MultiIndex.from_product([all_times, research.targets], names=("time", "asset"))
    values = []
    present_values = []
    available_values = []
    reasons = []
    grouped = {
        asset: source.xs(asset, level="asset", drop_level=False)
        for asset in source.index.get_level_values("asset").unique()
    }
    for point, asset in keys:
        rows = grouped.get(asset)
        candidates = (
            rows.loc[rows.index.get_level_values("time") <= point] if rows is not None else None
        )
        if candidates is not None and classification:
            candidates = candidates.loc[candidates["effective_at"] <= point]
        if candidates is None or candidates.empty:
            values.append(float("nan"))
            present_values.append(False)
            available_values.append(pd.NaT)
            reasons.append("MISSING_FIELD" if not classification else "UNKNOWN_CLASSIFICATION")
            continue

        visible = candidates.loc[candidates["available_at"] <= point]
        if visible.empty:
            selected = candidates.sort_values(["available_at"], kind="mergesort").iloc[0]
            values.append(float("nan"))
            present_values.append(True)
            available_values.append(selected["available_at"])
            reasons.append("NOT_YET_AVAILABLE")
            continue

        selected = visible.sort_index(level="time", kind="mergesort").iloc[-1]
        value = selected[value_column]
        values.append(value)
        present_values.append(True)
        available_values.append(selected["available_at"])
        reasons.append(
            "READY"
            if pd.notna(value)
            else ("UNKNOWN_CLASSIFICATION" if classification else "MISSING_FIELD")
        )

    values_frame = pd.DataFrame({value_column: values}, index=keys)
    present_series = pd.Series(present_values, index=keys, dtype=bool, name="present")
    available_series = pd.Series(
        pd.to_datetime(available_values, utc=True), index=keys, name="available_at"
    )
    reason_series = pd.Series(reasons, index=keys, dtype=object, name="reason")
    return AlignedPITInput(
        name=name,
        values=values_frame,
        present=present_series,
        available_at=available_series,
        reason=reason_series,
        classification=classification,
    )


__all__ = ("AlignedBars", "AlignedPITInput", "prealign_bars", "prealign_pit_table")
