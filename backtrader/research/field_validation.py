"""Point-in-time source metadata checks for formula-sensitive fields.

Formula table DataFrames carry declarations in ``attrs["source_metadata"]``.
For a single logical field the value is one metadata mapping; for a multi-line
feed DataFrame it is a mapping from logical field name to metadata mapping.
These declarations validate the input contract only. They do not prove how an
upstream source produced its values.
"""

from __future__ import annotations

import re
from copy import deepcopy
from collections.abc import Mapping, Sequence
from typing import Any, Iterable, NoReturn, Optional, Set, Tuple, cast

from ..errors import ResearchConfigError, DatasetError
from .specs import require_research_runtime

_FEED_ALIGNMENT = "_factor_research_alignment_v1"
_ADV_NAME = re.compile(r"adv([0-9]+)\Z")


def validate_factor_field_metadata(
    spec: Any,
    research: Any,
    datas: Iterable[Any],
    target_datas: Iterable[Any],
) -> None:
    """Validate metadata for direct/derived ADV and VWAP-dollar-volume inputs.

    The caller invokes this at FactorStrategy binding time, before constructing
    an indicator tree.  Direct ``advN`` values are treated as already computed
    fields: this function validates their declared provenance and never adds a
    rolling operation.  Only the registered ``derive="adv"`` binding is
    allowed to introduce a rolling mean elsewhere in the factor engine.

    ``DataFrame.attrs["source_metadata"]`` is read from formula tables and
    source feed DataFrames.  Formula tables retain their existing
    ``value``, ``available_at`` and ``data_version`` columns; these checks do
    not replace the cell-level PIT alignment performed by the input layer.
    """

    field_bindings = getattr(spec, "field_bindings", None)
    if not isinstance(field_bindings, Mapping):
        return

    formula_fields = getattr(research, "formula_fields", {})
    if not isinstance(formula_fields, Mapping):
        formula_fields = {}
    all_datas = tuple(datas)
    all_targets = tuple(target_datas)
    for alias, binding in field_bindings.items():
        adv_match = _ADV_NAME.fullmatch(alias) if isinstance(alias, str) else None
        if adv_match:
            window = int(adv_match.group(1))
            if window < 1:
                raise ResearchConfigError("ADV field names must declare a positive window")
            if isinstance(binding, Mapping) and binding.get("derive") == "adv":
                source_alias = binding.get("source")
                source_binding = field_bindings.get(source_alias)
                _validate_dollar_volume_source(
                    source_alias,
                    source_binding,
                    field_bindings,
                    formula_fields,
                    all_datas,
                    all_targets,
                    research=research,
                    factor_name=getattr(spec, "name", ""),
                )
            else:
                _validate_direct_adv(
                    alias,
                    window,
                    binding,
                    formula_fields,
                    all_datas,
                    all_targets,
                    research=research,
                    factor_name=getattr(spec, "name", ""),
                )
        elif alias == "dollar_volume":
            _validate_dollar_volume_source(
                alias,
                binding,
                field_bindings,
                formula_fields,
                all_datas,
                all_targets,
                research=research,
                factor_name=getattr(spec, "name", ""),
            )


def collect_bound_feed_tables(
    specs: Any,
    research: Any,
    datas: Iterable[Any],
    target_datas: Iterable[Any],
    *,
    observed_feed_inputs: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Collect the actual feed rows explicitly named by factor field bindings.

    Returned tables use the formula-input schema: ``value``, ``available_at``
    and ``data_version`` on a UTC ``(time, asset)`` index.  Source rows on the
    full ResearchSpec grid are retained when available, including label-tail
    bars; otherwise the exposed calculation grid is used. A target binding combines its target
    feeds; a named feed is broadcast over the research targets and records its
    original name in the ``source_feed`` column and source metadata.

    The helper does not infer field bindings from indicator code. Prealigned
    feeds use their immutable alignment marker; otherwise availability comes
    from an explicit row column or the declared ``close_time`` feed contract.
    The source version comes from a row column, alignment marker, field
    ``source_version`` or the explicit ResearchSpec ``snapshot_id``; its
    origin is recorded in ``source_metadata.data_version_source``. An optional
    observed-input mapping can supply real collected values and their actual
    times/versions. It is keyed by canonical binding and contains either a
    formula-input DataFrame or a mapping from ``(time, asset)`` to records
    with those required fields.
    """

    pd = require_research_runtime()
    all_datas = tuple(datas)
    all_targets = tuple(target_datas)
    target_names = tuple(getattr(research, "targets", ()))
    if len(target_names) != len(all_targets):
        raise ResearchConfigError("target feeds must match ResearchSpec.targets order")

    full_grid = getattr(research, "grid", None)
    calculation_grid = getattr(research, "calculation_grid", None)
    if isinstance(full_grid, pd.DataFrame):
        grid_frame = full_grid
        full_grid_requested = True
    elif isinstance(calculation_grid, pd.DataFrame):
        grid_frame = calculation_grid
        full_grid_requested = False
    else:
        raise ResearchConfigError("research must expose a calculation_grid or grid DataFrame")
    grid = _utc_index(grid_frame.index, research, pd, "source grid")
    grid_positions = {point: index for index, point in enumerate(grid)}
    fallback = observed_feed_inputs or {}
    if not isinstance(fallback, Mapping):
        raise ResearchConfigError("observed_feed_inputs must be a canonical-binding mapping")

    bindings = _explicit_feed_bindings(specs)
    output: dict = {}
    for binding in sorted(bindings):
        feed_name, line_name = _parse_feed_binding(binding)
        if feed_name == "target":
            feed_assets = tuple(zip(target_names, all_targets))
        else:
            named = tuple(data for data in all_datas if getattr(data, "_name", "") == feed_name)
            if len(named) != 1:
                raise DatasetError(
                    "bound formula feed is missing or ambiguous",
                    code="MISSING_INPUT",
                    report={"source_binding": binding, "feed": feed_name},
                )
            feed_assets = tuple((asset, named[0]) for asset in target_names)

        rows = []
        metadata_records = []
        for asset, feed in feed_assets:
            frame = getattr(getattr(feed, "p", None), "dataname", None)
            alignment = getattr(feed, _FEED_ALIGNMENT, None)
            if full_grid_requested and isinstance(alignment, Mapping):
                full_frame = alignment.get("full_frame")
                full_present = alignment.get("full_present")
                full_available = alignment.get("full_available_at")
                if not _is_dataframe(full_frame, pd):
                    raise DatasetError(
                        "prealigned feed does not expose its full source-grid frame",
                        code="MISSING_INPUT",
                        report={
                            "source_binding": binding,
                            "feed": getattr(feed, "_name", feed_name),
                        },
                    )
                if (
                    not isinstance(full_present, (tuple, list))
                    or not isinstance(full_available, (tuple, list))
                    or len(full_present) != len(grid)
                    or len(full_available) != len(grid)
                ):
                    raise DatasetError(
                        "prealigned feed does not expose full-grid PIT markers",
                        code="MISSING_INPUT",
                        report={
                            "source_binding": binding,
                            "feed": getattr(feed, "_name", feed_name),
                        },
                    )
                frame = full_frame
            source_record = _line_metadata(frame, line_name)
            if source_record is not None:
                metadata_records.append((getattr(feed, "_name", feed_name), source_record))
            if _is_dataframe(frame, pd):
                rows.extend(
                    _collect_dataframe_rows(
                        binding,
                        line_name,
                        frame,
                        feed,
                        asset,
                        research,
                        grid,
                        grid_positions,
                        source_record,
                        pd,
                    )
                )
                continue
            observed = fallback.get(binding)
            if observed is None:
                raise DatasetError(
                    "bound feed source has no collectable public frame or observed rows",
                    code="MISSING_INPUT",
                    report={"source_binding": binding, "feed": getattr(feed, "_name", feed_name)},
                )
            rows.extend(
                _collect_observed_rows(
                    binding,
                    observed,
                    asset,
                    grid_positions,
                    research,
                    pd,
                )
            )

        if not rows:
            raise DatasetError(
                "bound feed source has no rows on the calculation grid",
                code="MISSING_INPUT",
                report={"source_binding": binding},
            )
        result = pd.DataFrame.from_records(
            rows,
            columns=(
                "time",
                "asset",
                "value",
                "available_at",
                "data_version",
                "data_version_source",
                "source_feed",
            ),
        )
        result = result.set_index(["time", "asset"]).sort_index(kind="mergesort")
        if result.index.has_duplicates:
            raise DatasetError(
                "bound feed source produced duplicate calculation-grid rows",
                code="INVALID_DATASET",
                report={"source_binding": binding},
            )
        result["available_at"] = pd.to_datetime(result["available_at"], utc=True)
        metadata = _combined_source_metadata(binding, feed_name, metadata_records)
        version_sources = result["data_version_source"].dropna().unique().tolist()
        if len(version_sources) == 1:
            metadata["data_version_source"] = version_sources[0]
        else:
            for source_feed, versions in result.groupby("source_feed")["data_version_source"]:
                unique_sources = versions.dropna().unique().tolist()
                if len(unique_sources) == 1:
                    metadata["data_version_source.%s" % source_feed] = unique_sources[0]
        result.attrs = {"source_metadata": metadata}
        output[binding] = result
    return output


def _explicit_feed_bindings(specs: Any) -> set:
    if specs is None:
        return set()
    if isinstance(specs, Mapping):
        iterable = specs.values()
    else:
        try:
            iterable = iter(specs)
        except TypeError as exc:
            raise ResearchConfigError(
                "specs must be FactorSpecs or a mapping of FactorSpecs"
            ) from exc
    sources: Set[str] = set()
    for spec in iterable:
        field_bindings = getattr(spec, "field_bindings", None)
        if not isinstance(field_bindings, Mapping):
            continue
        for binding in field_bindings.values():
            _expand_binding_sources(binding, field_bindings, sources, set())
    return {source for source in sources if source.startswith("feed:")}


def _expand_binding_sources(
    binding: Any, field_bindings: Mapping[str, Any], result: set, seen: set
) -> None:
    if isinstance(binding, str):
        if binding.startswith("feed:"):
            result.add(binding)
        return
    if not isinstance(binding, Mapping):
        return
    if binding.get("kind") == "direct":
        _expand_binding_sources(binding.get("source"), field_bindings, result, seen)
    elif binding.get("derive") == "adv":
        alias = binding.get("source")
        if isinstance(alias, str) and alias not in seen:
            nested = field_bindings.get(alias)
            if nested is not None:
                _expand_binding_sources(nested, field_bindings, result, seen | {alias})
    elif binding.get("derive") == "vwap_volume":
        for alias in (binding.get("vwap"), binding.get("volume")):
            if isinstance(alias, str) and alias not in seen:
                nested = field_bindings.get(alias)
                if nested is not None:
                    _expand_binding_sources(nested, field_bindings, result, seen | {alias})


def _parse_feed_binding(binding: str) -> Tuple[str, str]:
    parts = binding.split(":")
    if len(parts) != 3 or parts[0] != "feed" or not parts[1] or not parts[2]:
        raise ResearchConfigError("feed bindings must use 'feed:<name>:<line>'")
    return parts[1], parts[2]


def _is_dataframe(value: Any, pd: Any) -> bool:
    return isinstance(value, pd.DataFrame)


def _utc_index(values: Any, research: Any, pd: Any, label: str) -> Any:
    try:
        index = pd.DatetimeIndex(pd.to_datetime(values, errors="raise"))
        if index.tz is None:
            index = index.tz_localize(
                research.source_timezone, ambiguous="raise", nonexistent="raise"
            )
        return index.tz_convert("UTC")
    except Exception as exc:
        raise DatasetError(
            "%s must contain unambiguous timestamps in the declared source timezone" % label,
            code="MISSING_INPUT",
        ) from exc


def _line_metadata(frame: Any, line_name: str) -> Optional[Mapping[str, Any]]:
    attrs = getattr(frame, "attrs", None)
    source_metadata = attrs.get("source_metadata") if isinstance(attrs, Mapping) else None
    if not isinstance(source_metadata, Mapping):
        return None
    if "name" in source_metadata:
        return source_metadata
    field_map = source_metadata.get("fields", source_metadata)
    if not isinstance(field_map, Mapping):
        return None
    record = field_map.get(line_name)
    return record if isinstance(record, Mapping) else None


def _line_column(frame: Any, feed: Any, line_name: str) -> Any:
    if line_name in frame.columns:
        return frame[line_name]
    mapping = getattr(feed, "_colmapping", {})
    column = mapping.get(line_name) if isinstance(mapping, Mapping) else None
    if isinstance(column, str) and column in frame.columns:
        return frame[column]
    if type(column) is int and 0 <= column < len(frame.columns):
        return frame.iloc[:, column]
    return None


def _collect_dataframe_rows(
    binding: str,
    line_name: str,
    frame: Any,
    feed: Any,
    asset: str,
    research: Any,
    grid: Any,
    grid_positions: Mapping[Any, int],
    metadata: Optional[Mapping[str, Any]],
    pd: Any,
) -> list:
    if isinstance(frame.index, pd.MultiIndex):
        raise DatasetError(
            "bound feed DataFrame must have a timestamp index",
            code="MISSING_INPUT",
            report={"source_binding": binding},
        )
    times = _utc_index(frame.index, research, pd, "bound feed index")
    if not times.is_unique:
        raise DatasetError(
            "bound feed DataFrame contains duplicate timestamps",
            code="INVALID_DATASET",
            report={"source_binding": binding},
        )
    values = _line_column(frame, feed, line_name)
    if values is None:
        raise DatasetError(
            "bound feed DataFrame does not expose the declared line",
            code="MISSING_INPUT",
            report={"source_binding": binding},
        )

    aligned = getattr(feed, _FEED_ALIGNMENT, None)
    marker = isinstance(aligned, Mapping)
    aligned_mapping = cast(Mapping[str, Any], aligned) if marker else {}
    full_marker = marker and frame is aligned_mapping.get("full_frame")
    present_values: Sequence[Any] = ()
    available_values: Sequence[Any] = ()
    marker_version = None
    if marker:
        if aligned_mapping.get("grid_sha256") != getattr(research, "grid_sha256", None):
            raise DatasetError(
                "prealigned feed marker belongs to a different calculation grid",
                code="INVALID_DATASET",
                report={"source_binding": binding},
            )
        present_key = "full_present" if full_marker else "present"
        available_key = "full_available_at" if full_marker else "available_at"
        raw_present = aligned_mapping.get(present_key)
        raw_available = aligned_mapping.get(available_key)
        marker_version = aligned_mapping.get("data_version")
        if (
            not isinstance(raw_present, (tuple, list))
            or not isinstance(raw_available, (tuple, list))
            or len(raw_present) != len(grid)
            or len(raw_available) != len(grid)
        ):
            raise DatasetError(
                "prealigned feed marker has incomplete per-grid PIT metadata",
                code="MISSING_INPUT",
                report={"source_binding": binding},
            )
        present_values = cast(Sequence[Any], raw_present)
        available_values = cast(Sequence[Any], raw_available)

    output = []
    for source_index, point in enumerate(times):
        grid_position = grid_positions.get(point)
        if grid_position is None:
            continue
        if marker and not bool(present_values[grid_position]):
            continue
        value = values.iloc[source_index]
        available_at = None
        if "available_at" in frame.columns:
            available_at = frame["available_at"].iloc[source_index]
        if (available_at is None or _is_missing(available_at, pd)) and marker:
            available_at = available_values[grid_position]
        if (available_at is None or _is_missing(available_at, pd)) and (
            (metadata is not None and metadata.get("availability") == "bar_close")
            or getattr(research, "feed_time_kind", None) == "close_time"
        ):
            available_at = point
        if available_at is None or _is_missing(available_at, pd):
            raise DatasetError(
                "bound feed row has no declared or observed availability timestamp",
                code="MISSING_INPUT",
                report={"source_binding": binding, "time": point.isoformat(), "asset": asset},
            )
        stamp = _utc_timestamp(available_at, research.source_timezone, pd, binding)

        version = None
        version_source = None
        if "data_version" in frame.columns:
            version = frame["data_version"].iloc[source_index]
            if not _is_missing(version, pd):
                version_source = "feed.data_version"
        if (version is None or _is_missing(version, pd)) and marker:
            version = marker_version
            if not _is_missing(version, pd):
                version_source = "alignment_marker.data_version"
        if (version is None or _is_missing(version, pd)) and metadata is not None:
            version = metadata.get("source_version")
            if version is not None:
                version_source = "source_metadata.source_version"
        if version is None or _is_missing(version, pd):
            # snapshot_id is an explicit ResearchSpec declaration for this
            # immutable input snapshot, not a generated per-feed version.
            version = getattr(research, "snapshot_id", None)
            if version is not None:
                version_source = "research.snapshot_id"
        if not isinstance(version, str) or not version.strip():
            raise DatasetError(
                "bound feed row has no declared data version",
                code="MISSING_INPUT",
                report={"source_binding": binding, "time": point.isoformat(), "asset": asset},
            )
        output.append(
            {
                "time": grid[grid_position],
                "asset": asset,
                "value": value,
                "available_at": stamp,
                "data_version": version.strip(),
                "data_version_source": version_source,
                "source_feed": getattr(feed, "_name", ""),
            }
        )
    return output


def _collect_observed_rows(
    binding: str,
    observed: Any,
    asset: str,
    grid_positions: Mapping[Any, int],
    research: Any,
    pd: Any,
) -> list:
    if isinstance(observed, pd.DataFrame):
        frame = observed.copy(deep=True)
        if not isinstance(frame.index, pd.MultiIndex) or tuple(frame.index.names) != (
            "time",
            "asset",
        ):
            raise DatasetError(
                "observed feed fallback must use a (time, asset) index",
                code="MISSING_INPUT",
                report={"source_binding": binding},
            )
        if not {"value", "available_at", "data_version"}.issubset(frame.columns):
            raise DatasetError(
                "observed feed fallback has an incomplete PIT schema",
                code="MISSING_INPUT",
                report={"source_binding": binding},
            )
        items = frame.iterrows()
    elif isinstance(observed, Mapping):
        items = observed.items()
    else:
        raise ResearchConfigError("observed feed fallback values must be a DataFrame or mapping")

    output = []
    for key, record in items:
        if isinstance(observed, pd.DataFrame):
            time, row_asset = key
            values = record
        else:
            if not isinstance(key, tuple) or len(key) != 2:
                raise ResearchConfigError("observed feed keys must be (time, asset) pairs")
            time, row_asset = key
            values = record
        point = _utc_timestamp(time, research.source_timezone, pd, binding)
        if point not in grid_positions or row_asset != asset:
            continue
        if not isinstance(values, Mapping) and not hasattr(values, "get"):
            raise ResearchConfigError("observed feed records must expose value/PIT fields")
        value = values.get("value")
        available_at = values.get("available_at")
        version = values.get("data_version")
        if available_at is None or _is_missing(available_at, pd):
            raise DatasetError(
                "observed feed row has no actual availability timestamp",
                code="MISSING_INPUT",
                report={"source_binding": binding, "asset": asset},
            )
        if not isinstance(version, str) or not version.strip():
            raise DatasetError(
                "observed feed row has no data version",
                code="MISSING_INPUT",
                report={"source_binding": binding, "asset": asset},
            )
        version_source = values.get("data_version_source", "observed_feed_inputs.data_version")
        output.append(
            {
                "time": point,
                "asset": asset,
                "value": value,
                "available_at": _utc_timestamp(available_at, research.source_timezone, pd, binding),
                "data_version": version.strip(),
                "data_version_source": version_source,
                "source_feed": values.get("source_feed", "observed"),
            }
        )
    return output


def _combined_source_metadata(
    binding: str,
    declared_feed: str,
    records: Iterable[Tuple[str, Mapping[str, Any]]],
) -> dict:
    records = tuple(records)
    common: dict = {}
    per_feed: dict = {}
    keys = set().union(*(set(record) for _, record in records)) if records else set()
    for key in keys:
        values = [(feed, record[key]) for feed, record in records if key in record]
        if values and all(value == values[0][1] for _, value in values):
            common[key] = deepcopy(values[0][1])
        else:
            for feed, value in values:
                per_feed["%s.%s" % (feed, key)] = deepcopy(value)
    common.update(per_feed)
    common["source_binding"] = binding
    common["source_feed"] = declared_feed
    return common


def _is_missing(value: Any, pd: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _utc_timestamp(value: Any, source_timezone: str, pd: Any, label: str) -> Any:
    try:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            stamp = stamp.tz_localize(source_timezone, ambiguous="raise", nonexistent="raise")
        return stamp.tz_convert("UTC")
    except Exception as exc:
        raise DatasetError(
            "%s must contain an unambiguous actual timestamp" % label,
            code="MISSING_INPUT",
        ) from exc


def _validate_direct_adv(
    alias: str,
    window: int,
    binding: Any,
    formula_fields: Mapping[str, Any],
    datas: Tuple[Any, ...],
    target_datas: Tuple[Any, ...],
    *,
    research: Any,
    factor_name: str,
) -> None:
    records = _records_for_binding(
        alias,
        binding,
        formula_fields,
        datas,
        target_datas,
        factor_name=factor_name,
    )
    for record, frame, source_kind, feed in records:
        _require_equal(alias, record, "name", alias, factor_name=factor_name)
        _require_equal(
            alias,
            record,
            "semantic",
            "average_daily_dollar_volume",
            factor_name=factor_name,
        )
        _require_equal(alias, record, "unit", "USD", factor_name=factor_name)
        _require_equal(alias, record, "currency", "USD", factor_name=factor_name)
        _require_text(alias, record, "adjustment", factor_name=factor_name)
        _require_equal(alias, record, "statistic", "mean", factor_name=factor_name)
        if "window" not in record:
            _missing_metadata(factor_name, alias, ("window",))
        metadata_window = record.get("window")
        if type(metadata_window) is not int or metadata_window != window:
            raise ResearchConfigError("direct %s metadata window must match its field name" % alias)
        if "complete_window" not in record:
            _missing_metadata(factor_name, alias, ("complete_window",))
        if record.get("complete_window") is not True:
            raise ResearchConfigError(
                "direct %s metadata must declare complete_window=True" % alias
            )
        _require_text(alias, record, "source_version", factor_name=factor_name)
        if "provenance_source_lookback_grid_bars" not in record:
            _missing_metadata(factor_name, alias, ("provenance_source_lookback_grid_bars",))
        source_span = record.get("provenance_source_lookback_grid_bars")
        if type(source_span) is not int or source_span != window - 1:
            raise ResearchConfigError(
                "direct %s provenance span must be window-1 grid bars" % alias
            )
        _require_pit_columns(
            alias,
            frame,
            source_kind,
            feed,
            record,
            research=research,
            factor_name=factor_name,
        )


def _validate_dollar_volume_source(
    alias: Any,
    binding: Any,
    field_bindings: Mapping[str, Any],
    formula_fields: Mapping[str, Any],
    datas: Tuple[Any, ...],
    target_datas: Tuple[Any, ...],
    *,
    research: Any,
    factor_name: str,
) -> None:
    if alias != "dollar_volume" or binding is None:
        raise DatasetError(
            "derived ADV requires an explicit dollar_volume source",
            code="MISSING_INPUT",
            report={"factor": factor_name, "field": "dollar_volume"},
        )

    if isinstance(binding, Mapping) and binding.get("derive") == "vwap_volume":
        if set(binding) != {"derive", "vwap", "volume"}:
            raise ResearchConfigError("vwap_volume requires derive/vwap/volume only")
        vwap_alias = binding.get("vwap")
        volume_alias = binding.get("volume")
        if not isinstance(vwap_alias, str) or not isinstance(volume_alias, str):
            raise ResearchConfigError("vwap_volume source aliases must be strings")
        vwap_records = _records_for_binding(
            vwap_alias,
            field_bindings.get(vwap_alias),
            formula_fields,
            datas,
            target_datas,
            factor_name=factor_name,
        )
        volume_records = _records_for_binding(
            volume_alias,
            field_bindings.get(volume_alias),
            formula_fields,
            datas,
            target_datas,
            factor_name=factor_name,
        )
        if len(vwap_records) != len(volume_records):
            raise ResearchConfigError("vwap_volume inputs must resolve to the same source count")
        for (vwap, vwap_frame, vwap_kind, vwap_feed), (
            volume,
            volume_frame,
            volume_kind,
            volume_feed,
        ) in zip(vwap_records, volume_records):
            _require_equal(
                vwap_alias,
                vwap,
                "name",
                "vwap",
                factor_name=factor_name,
            )
            _require_equal(
                vwap_alias,
                vwap,
                "semantic",
                "volume_weighted_average_price",
                factor_name=factor_name,
            )
            _require_equal(vwap_alias, vwap, "unit", "USD per share", factor_name=factor_name)
            _require_equal(vwap_alias, vwap, "currency", "USD", factor_name=factor_name)
            _require_equal(
                vwap_alias,
                vwap,
                "statistic",
                "trade_volume_weighted_mean",
                factor_name=factor_name,
            )
            adjustment = _require_text(vwap_alias, vwap, "adjustment", factor_name=factor_name)

            _require_equal(
                volume_alias,
                volume,
                "name",
                "volume",
                factor_name=factor_name,
            )
            _require_equal(
                volume_alias,
                volume,
                "semantic",
                "share_volume",
                factor_name=factor_name,
            )
            _require_equal(volume_alias, volume, "unit", "shares", factor_name=factor_name)
            volume_adjustment = _require_text(
                volume_alias, volume, "adjustment", factor_name=factor_name
            )
            if volume_adjustment != adjustment:
                raise ResearchConfigError("vwap and volume adjustment metadata must match")
            _require_pit_columns(
                vwap_alias,
                vwap_frame,
                vwap_kind,
                vwap_feed,
                vwap,
                research=research,
                factor_name=factor_name,
            )
            _require_pit_columns(
                volume_alias,
                volume_frame,
                volume_kind,
                volume_feed,
                volume,
                research=research,
                factor_name=factor_name,
            )
        return

    records = _records_for_binding(
        "dollar_volume",
        binding,
        formula_fields,
        datas,
        target_datas,
        factor_name=factor_name,
    )
    for record, frame, source_kind, feed in records:
        _require_equal(
            "dollar_volume",
            record,
            "name",
            "dollar_volume",
            factor_name=factor_name,
        )
        _require_equal(
            "dollar_volume",
            record,
            "semantic",
            "daily_dollar_volume",
            factor_name=factor_name,
        )
        _require_equal("dollar_volume", record, "unit", "USD", factor_name=factor_name)
        _require_equal("dollar_volume", record, "currency", "USD", factor_name=factor_name)
        _require_text("dollar_volume", record, "adjustment", factor_name=factor_name)
        _require_pit_columns(
            "dollar_volume",
            frame,
            source_kind,
            feed,
            record,
            research=research,
            factor_name=factor_name,
        )


def _records_for_binding(
    alias: str,
    binding: Any,
    formula_fields: Mapping[str, Any],
    datas: Tuple[Any, ...],
    target_datas: Tuple[Any, ...],
    *,
    factor_name: str,
) -> Tuple[Tuple[Mapping[str, Any], Any, str, Any], ...]:
    source = _direct_source(binding)
    if not isinstance(source, str):
        raise ResearchConfigError("%s requires a direct source binding" % alias)
    if source.startswith("table:"):
        table_name = source.split(":", 1)[1]
        frame = formula_fields.get(table_name)
        if frame is None:
            raise DatasetError(
                "formula field metadata references an unknown table",
                code="MISSING_INPUT",
                report={"factor": factor_name, "field": alias, "table": table_name},
            )
        metadata = _metadata_record(frame, alias, field_name=None, factor_name=factor_name)
        return ((metadata, frame, "table", None),)
    if not source.startswith("feed:"):
        raise ResearchConfigError("%s source must use a qualified feed or table binding" % alias)
    pieces = source.split(":")
    if len(pieces) != 3 or not pieces[1] or not pieces[2]:
        raise ResearchConfigError("feed binding must use 'feed:<name>:<line>'")
    feed_name, line_name = pieces[1], pieces[2]
    if feed_name == "target":
        feeds = target_datas
    else:
        feeds = tuple(data for data in datas if getattr(data, "_name", "") == feed_name)
    if not feeds:
        raise DatasetError(
            "formula field metadata references an unknown feed",
            code="MISSING_INPUT",
            report={"factor": factor_name, "field": alias, "feed": feed_name},
        )
    records = []
    for feed in feeds:
        frame = getattr(getattr(feed, "p", None), "dataname", None)
        metadata = _metadata_record(
            frame,
            alias,
            field_name=line_name,
            factor_name=factor_name,
        )
        records.append((metadata, frame, "feed", feed))
    return tuple(records)


def _direct_source(binding: Any) -> Any:
    if isinstance(binding, Mapping):
        if binding.get("kind") == "direct":
            return binding.get("source")
        return None
    return binding


def _metadata_record(
    frame: Any,
    alias: str,
    *,
    field_name: Optional[str],
    factor_name: str,
) -> Mapping[str, Any]:
    attrs = getattr(frame, "attrs", None)
    source_metadata = attrs.get("source_metadata") if isinstance(attrs, Mapping) else None
    if not isinstance(source_metadata, Mapping):
        _missing_metadata(factor_name, alias, ("source_metadata",))
    source_metadata = cast(Mapping[str, Any], source_metadata)
    record: Any
    if "name" in source_metadata:
        record = source_metadata
    else:
        field_map = source_metadata.get("fields", source_metadata)
        if not isinstance(field_map, Mapping):
            _missing_metadata(factor_name, alias, ("source_metadata.fields",))
        field_map = cast(Mapping[str, Any], field_map)
        record = field_map.get(alias)
        if record is None and field_name is not None:
            record = field_map.get(field_name)
    if not isinstance(record, Mapping):
        _missing_metadata(factor_name, alias, ("source_metadata record",))
    return record


def _require_pit_columns(
    alias: str,
    frame: Any,
    source_kind: str,
    feed: Any,
    metadata: Mapping[str, Any],
    *,
    research: Any,
    factor_name: str,
) -> None:
    if source_kind == "table":
        columns = getattr(frame, "columns", ())
        missing = tuple(name for name in ("available_at", "data_version") if name not in columns)
        if missing:
            _missing_metadata(factor_name, alias, missing)
        if len(frame.index) == 0:
            _missing_metadata(factor_name, alias, ("rows",))
        available = frame["available_at"]
        versions = frame["data_version"]
        if bool(available.isna().any()):
            _missing_metadata(factor_name, alias, ("available_at values",))
        if bool(versions.isna().any()) or any(
            not isinstance(value, str) or not value.strip() for value in versions
        ):
            _missing_metadata(factor_name, alias, ("data_version values",))
        return

    aligned = getattr(feed, _FEED_ALIGNMENT, None)
    # ``prealign_bars`` stores the PIT facts on the feed, not on its source
    # DataFrame. The source frame can still declare an explicit bar-close
    # availability contract when it is used directly.
    available_at_present = False
    if isinstance(aligned, Mapping):
        available = aligned.get("available_at")
        available_at_present = isinstance(available, (tuple, list)) and any(
            value is not None for value in available
        )
    columns = getattr(frame, "columns", ())
    if "available_at" in columns:
        values = frame["available_at"]
        notna = getattr(values, "notna", None)
        available_at_present = available_at_present or (callable(notna) and bool(notna().any()))
    if not available_at_present and metadata.get("availability") != "bar_close":
        if getattr(research, "feed_time_kind", None) != "close_time":
            _missing_metadata(factor_name, alias, ("available_at",))

    version_present = False
    if "data_version" in columns:
        versions = frame["data_version"]
        notna = getattr(versions, "notna", None)
        version_present = callable(notna) and bool(notna().any())
    if isinstance(aligned, Mapping):
        marker_version = aligned.get("data_version")
        version_present = version_present or (
            isinstance(marker_version, str) and bool(marker_version.strip())
        )
    source_version = metadata.get("source_version")
    version_present = version_present or (
        isinstance(source_version, str) and bool(source_version.strip())
    )
    snapshot_id = getattr(research, "snapshot_id", None)
    version_present = version_present or (
        isinstance(snapshot_id, str) and bool(snapshot_id.strip())
    )
    if not version_present:
        _missing_metadata(factor_name, alias, ("data_version",))


def _require_equal(
    alias: str,
    metadata: Mapping[str, Any],
    key: str,
    expected: Any,
    *,
    factor_name: str,
) -> None:
    if key not in metadata:
        _missing_metadata(factor_name, alias, (key,))
    actual = metadata[key]
    if type(expected) is str:
        compatible = isinstance(actual, str) and actual == expected
    else:
        compatible = type(actual) is type(expected) and actual == expected
    if not compatible:
        raise ResearchConfigError("%s source metadata %s is incompatible" % (alias, key))


def _require_text(
    alias: str,
    metadata: Mapping[str, Any],
    key: str,
    *,
    factor_name: str,
) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        if key not in metadata:
            _missing_metadata(factor_name, alias, (key,))
        raise ResearchConfigError("%s source metadata %s must be a non-empty string" % (alias, key))
    return value.strip()


def _missing_metadata(factor_name: str, alias: str, missing: Tuple[str, ...]) -> NoReturn:
    raise DatasetError(
        "formula field source metadata is incomplete",
        code="MISSING_INPUT",
        report={"factor": factor_name, "field": alias, "missing_metadata": missing},
    )


__all__ = ("collect_bound_feed_tables", "validate_factor_field_metadata")
