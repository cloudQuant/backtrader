"""Native Backtrader strategy that collects a plain-frame research panel."""

from __future__ import annotations

import math
import sys
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

from .. import Strategy
from ..utils import date2num, num2date
from ..errors import ResearchConfigError, DatasetError
from ..lineiterator import LineIterator
from ..metabase import OwnerContext
from ..research.factor_indicator import FactorIndicator
from ..research.specs import (
    FactorSpec,
    ResearchSpec,
    normalize_factor_specs,
    require_research_runtime,
    thaw,
)

_ALIGNMENT_V1 = "_factor_research_alignment_v1"
_ALIGNMENT_V2 = "_factor_research_alignment_v2"


class _FactorGroupInstances:
    """Read-only aggregate for the native instance built per research group."""

    def __init__(
        self, instances: Mapping[str, FactorIndicator], target_datas: Sequence[Any]
    ) -> None:
        self.group_instances = dict(instances)
        self.datas = tuple(target_datas)
        self.target_datas = self.datas
        first_instance = next(iter(self.group_instances.values()), None)
        self.available_datas = tuple(getattr(first_instance, "available_datas", self.datas))
        outputs: Dict[Any, Any] = {}
        for instance in self.group_instances.values():
            outputs.update(instance.outputs)
        self.outputs = {data: outputs[data] for data in self.datas}

    @property
    def lifecycle_diagnostics(self) -> Dict[str, Any]:
        by_group = {
            group: instance.lifecycle_diagnostics
            for group, instance in self.group_instances.items()
        }
        return {
            "call_count": sum(item["call_count"] for item in by_group.values()),
            "call_times": tuple((group, item["call_times"]) for group, item in by_group.items()),
            "grid_count": max((item["grid_count"] for item in by_group.values()), default=0),
            "grid_matches": bool(by_group)
            and all(item["grid_matches"] for item in by_group.values()),
            "next_count": sum(item["next_count"] for item in by_group.values()),
            "next_times": tuple((group, item["next_times"]) for group, item in by_group.items()),
            "once_ranges": tuple((group, item["once_ranges"]) for group, item in by_group.items()),
            "once_count": sum(item["once_count"] for item in by_group.values()),
            "once_times": tuple((group, item["once_times"]) for group, item in by_group.items()),
            "coverage_count": sum(item["coverage_count"] for item in by_group.values()),
            "coverage_times": tuple(
                (group, item["coverage_times"]) for group, item in by_group.items()
            ),
            "coverage_matches": bool(by_group)
            and all(item["coverage_matches"] for item in by_group.values()),
            "group_diagnostics": by_group,
        }


class FactorStrategy(Strategy):
    """Construct native factor indicators and collect one :class:`FactorPanel`.

    Cerebro owns all indicator and feed clocks.  The strategy only samples the
    research window once per grid point into a :class:`FactorSink`; it never
    advances a factor, builds a second clock or records per-cell availability.
    """

    params = (("research", None), ("factors", None), ("sink", None))

    def __init__(self) -> None:
        try:
            self._initialize_research()
        except BaseException:
            sink = self.__dict__.get("_sink")
            if sink is not None:
                try:
                    sink.close()
                except BaseException:
                    pass
            raise

    def _initialize_research(self) -> None:
        self._research = self.p.research
        if not isinstance(self._research, ResearchSpec):
            raise ResearchConfigError("FactorStrategy requires research=ResearchSpec(...)")
        if not self.datas:
            raise ResearchConfigError("FactorStrategy requires named target data feeds")
        if self._research.start > self._research.end:
            raise ResearchConfigError("research start must not follow end")
        owns_sink = self.p.sink is None
        self._sink = self.p.sink
        if self._sink is None:
            from ..research.sink import MemorySink

            self._sink = MemorySink()
        else:
            from ..research.sink import FactorSink

            if not isinstance(self._sink, FactorSink):
                raise ResearchConfigError("sink must be a FactorSink instance")
        self._panel: Any = None
        self._defer_csv_publication = False
        self._pending_csv_panel: Any = None
        self._collection_failed = False
        self._panel_context_cache: Any = None
        self._present_cumsum: Dict[int, Any] = {}

        self._data_names = tuple(getattr(data, "_name", "") for data in self.datas)
        if any(not isinstance(name, str) or not name for name in self._data_names):
            raise ResearchConfigError("every FactorStrategy feed needs a non-empty Cerebro name")
        if len(set(self._data_names)) != len(self._data_names):
            raise ResearchConfigError("FactorStrategy feed names must be unique")
        self._validate_clocks()
        target_data = dict(zip(self._data_names, self.datas))
        missing = set(self._research.targets) - set(target_data)
        if missing:
            raise DatasetError(
                "ResearchSpec targets have no matching named feed",
                code="MISSING_INPUT",
                report={"missing_targets": tuple(sorted(missing))},
            )
        self._target_datas = tuple(target_data[name] for name in self._research.targets)
        self._asset_by_target_data_id = {
            id(data): asset for asset, data in zip(self._research.targets, self._target_datas)
        }

        self._factor_specs_by_name: Mapping[str, FactorSpec] = normalize_factor_specs(
            self.p.factors
        )
        self.factor_instances: Dict[str, Any] = {}
        self._factor_instances_by_name: Dict[str, Tuple[FactorIndicator, ...]] = {}
        self._factor_instance_by_data: Dict[str, Dict[int, FactorIndicator]] = {}
        self._factor_graphs: Dict[
            int, Tuple[Tuple[FactorIndicator, ...], Tuple[Tuple[Any, Any], ...]]
        ] = {}
        for name, spec in self._factor_specs_by_name.items():
            if spec.panel_line not in spec.indicator._factor_template_names():
                raise ResearchConfigError("factor %s selects an unknown panel_line" % name)
            self._validate_bindings(spec)
            assets_by_group: Dict[str, List[str]] = {}
            for asset in self._research.targets:
                group = self._research.groups[asset]
                assets_by_group.setdefault(group, []).append(asset)
            instances_by_group: Dict[str, FactorIndicator] = {}
            for group, assets in assets_by_group.items():
                group_datas = tuple(target_data[asset] for asset in assets)
                # Make the offline strategy the explicit construction owner.
                # Descendants retain their own indicator owner and are driven
                # through the ordinary Cerebro indicator lifecycle.
                with OwnerContext.set_owner(self):
                    instance = spec.indicator._bind_for_research(
                        *group_datas,
                        output_datas=group_datas,
                        asset_names=tuple(assets),
                        factor_name=name,
                        field_bindings=spec.field_bindings,
                        research=self._research,
                        mode=spec.mode,
                        available_datas=self.datas,
                        strict=True,
                        **thaw(spec.params),
                    )
                if instance._owner is not self:
                    raise RuntimeError("research factor was bound to a different owner")
                self.addindicator(instance)
                if sum(item is instance for item in self._lineiterators[LineIterator.IndType]) != 1:
                    raise RuntimeError("research factor must occur exactly once in the owner graph")
                graph = self._freeze_factor_graph(instance)
                for node in graph[0]:
                    node._bind_grid(self._calculation_times())
                self._factor_graphs[id(instance)] = graph
                instances_by_group[group] = instance
            instances = tuple(instances_by_group.values())
            self._factor_instances_by_name[name] = instances
            self._factor_instance_by_data[name] = {
                id(data): instance for instance in instances for data in instance.target_datas
            }
            if len(instances) == 1:
                self.factor_instances[name] = instances[0]
            else:
                self.factor_instances[name] = _FactorGroupInstances(
                    instances_by_group, self._target_datas
                )

        self._grid = self._calculation_times()
        self._grid_cursor = 0
        if owns_sink and type(self) is FactorStrategy and self._has_complete_price_alignment():
            from ..research.sink import MemorySink

            if type(self._sink) is MemorySink:
                start = self._research.start.to_pydatetime()
                end = self._research.end.to_pydatetime()
                study_steps = sum(start <= value <= end for value in self._grid)
                self._sink._enable_dense_product_index(study_steps * len(self._target_datas))
        # Keep the source feed as well as its field: the same line name can
        # occur on a target and on an explicitly bound input-only feed.
        self._input_sources_by_spec = {
            id(spec): tuple(
                (None if feed_name == "target" else id(target_data[feed_name]), alias)
                for feed_name, alias in _input_sources(spec)
            )
            for spec in self._factor_specs_by_name.values()
        }
        named_source_ids = {
            source_id
            for sources in self._input_sources_by_spec.values()
            for source_id, _ in sources
            if source_id is not None
        }
        self._named_source_datas = tuple(
            data for data in self.datas if id(data) in named_source_ids
        )
        self._required_input_fields: Dict[int, set] = {}
        for sources in self._input_sources_by_spec.values():
            for source_id, alias in sources:
                source_ids = (
                    (id(data) for data in self._target_datas) if source_id is None else (source_id,)
                )
                for required_id in source_ids:
                    self._required_input_fields.setdefault(required_id, set()).add(alias)
        self._field_counts = self._build_field_counts()
        self._validate_preloaded_named_source_clocks()

    def _start(self) -> None:
        try:
            super()._start()
        except BaseException:
            try:
                self._sink.close()
            except BaseException:
                pass
            raise

    def _calculation_times(self) -> Tuple[datetime, ...]:
        return tuple(value.to_pydatetime() for value in self._research.calculation_grid.index)

    def _has_complete_price_alignment(self) -> bool:
        """Check alignment shape without retaining or copying mutable price arrays."""
        grid = self._research.grid
        grid_size = len(grid.index)
        grid_sha256 = self._research.grid_sha256
        for data in self._target_datas:
            metadata = _alignment_metadata(data)
            if (
                not isinstance(metadata, Mapping)
                or metadata.get("version") != 2
                or metadata.get("grid_sha256") != grid_sha256
            ):
                return False
            for name in ("prices_open", "prices_close"):
                values = metadata.get(name)
                try:
                    if values is None or len(values) != grid_size:
                        return False
                except TypeError:
                    return False
        return True

    def _validate_clocks(self) -> None:
        cerebro = getattr(self, "env", None)
        if (
            bool(getattr(cerebro, "_doreplay", False))
            or bool(getattr(cerebro, "_dolive", False))
            or bool(getattr(getattr(cerebro, "p", None), "live", False))
        ):
            raise ResearchConfigError(
                "FactorStrategy does not support live or replay Cerebro clocks",
                code="UNSUPPORTED_CLOCK",
            )
        clocks = []
        for data in self.datas:
            live = getattr(data, "islive", None)
            if callable(live) and live():
                raise ResearchConfigError(
                    "FactorStrategy does not support live feed clocks",
                    code="UNSUPPORTED_CLOCK",
                )
            if bool(getattr(data, "replaying", False)) or bool(getattr(data, "resampling", False)):
                raise ResearchConfigError(
                    "FactorStrategy does not support replay or resampled feed clocks",
                    code="UNSUPPORTED_CLOCK",
                )
            clocks.append(
                (
                    getattr(data, "_timeframe", getattr(data.p, "timeframe", None)),
                    getattr(data, "_compression", getattr(data.p, "compression", None)),
                )
            )
        if clocks and any(clock != clocks[0] for clock in clocks[1:]):
            raise ResearchConfigError(
                "FactorStrategy requires one synchronized feed timeframe",
                code="UNSUPPORTED_CLOCK",
            )

    def _validate_bindings(self, spec: FactorSpec) -> None:
        for alias, binding in spec.field_bindings.items():
            if isinstance(binding, str):
                source = binding
            elif isinstance(binding, Mapping):
                if binding.get("derive") in ("adv", "vwap_volume"):
                    continue
                source = binding.get("source", "")
            else:
                raise ResearchConfigError("factor field bindings must be qualified")
            if not isinstance(source, str) or not source.startswith("feed:"):
                raise ResearchConfigError(
                    "factor field bindings must use feed:<name>:<line>; PIT/table inputs "
                    "are not supported"
                )
            parts = source.split(":")
            if len(parts) != 3 or (parts[1] != "target" and parts[1] not in self._data_names):
                raise DatasetError(
                    "factor field binding references an unknown feed",
                    code="MISSING_INPUT",
                    report={"factor": spec.name, "field": alias, "feed": parts[1]},
                )

    # -- collection ------------------------------------------------------

    def prenext(self) -> None:
        self._collect_current_grid_point()

    def nextstart(self) -> None:
        self._collect_current_grid_point()

    def next(self) -> None:
        self._collect_current_grid_point()

    def _collect_current_grid_point(self) -> None:
        try:
            self._collect_grid_point()
        except BaseException:
            self._collection_failed = True
            raise

    def _collect_grid_point(self) -> None:
        if self._grid_cursor >= len(self._grid):
            current = num2date(float(self.datetime[0]), tz=timezone.utc, naive=False)
            if current > self._grid[-1]:
                return
            raise RuntimeError("FactorStrategy received more callbacks than the declared grid")
        current_num = float(self.datetime[0])
        current = num2date(current_num, tz=timezone.utc, naive=False)
        if current != self._grid[self._grid_cursor]:
            raise RuntimeError("FactorStrategy callback time does not match the ResearchSpec grid")
        for source in self._named_source_datas:
            if self._current_feed_time(source, current_num, current) != current:
                raise DatasetError(
                    "factor source actual close clock does not match the research grid"
                )
        graphs = self._validate_research_ownership()
        # Refuse to read or publish a row until every factor in its native
        # graph has actually computed this point (or its once range).
        for instances in self._factor_instances_by_name.values():
            for root in instances:
                for node in graphs[id(root)]:
                    if (
                        node._factor_call_count + node._factor_once_covered_count
                        <= self._grid_cursor
                    ):
                        raise RuntimeError(
                            "research factor has not computed the current grid point"
                        )
                    if len(node) != self._grid_cursor + 1:
                        raise RuntimeError(
                            "research factor is not positioned at the current grid point"
                        )
        research = self._research
        in_research = research.start.to_pydatetime() <= current <= research.end.to_pydatetime()
        use_numeric_date_hint = type(self) is FactorStrategy
        for asset, data in zip(research.targets, self._target_datas):
            present = self._feed_present(data, self._grid_cursor)
            if use_numeric_date_hint:
                feed_time = self._current_feed_time(data, current_num, current)
            else:
                feed_time = self._current_feed_time(data)
            current_bar = feed_time == current and present
            if in_research:
                self._sink.on_point(
                    current,
                    asset,
                    self._point_values(data, asset, current, current_bar),
                    self._line_value(data, "open") if current_bar else float("nan"),
                    self._line_value(data, "close") if current_bar else float("nan"),
                    present,
                )
        self._grid_cursor += 1

    def _point_values(
        self, data: Any, asset: str, current: datetime, current_bar: bool
    ) -> Dict[str, float]:
        values: Dict[str, float] = {}
        cursor = self._grid_cursor
        for name, spec in self._factor_specs_by_name.items():
            value = float("nan")
            if current_bar and self._window_is_complete(data, cursor, spec):
                indicator = self._factor_instance_by_data[name][id(data)]
                value = float(indicator.outputs[data][spec.panel_line][0])
                if not math.isfinite(value):
                    value = float("nan")
            values[name] = value
        return values

    def _window_is_complete(self, data: Any, cursor: int, spec: FactorSpec) -> bool:
        """True when every bar and every declared input in the window is usable.

        A missing bar nulls its own grid point and the next ``lookback_h``
        points, and a present bar whose declared input value is non-finite does
        the same; this reproduces the previously published factor results
        without rebuilding the deleted per-cell availability table.  Per-field
        cumulative presence counts answer each query in constant time.
        """
        lookback = spec.lookback_h
        start = max(0, cursor - lookback)
        expected = cursor - start + 1
        sources = self._input_sources_by_spec[id(spec)]
        for source_id, alias in sources:
            counts = self._field_counts.get((id(data) if source_id is None else source_id, alias))
            if counts is None:
                continue
            if int(counts[cursor + 1] - counts[start]) != expected:
                return False
        return True

    def _build_field_counts(self) -> Dict[Any, Any]:
        import numpy as np

        counts: Dict[Any, Any] = {}
        expected_times = self._research.calculation_grid.index
        for data in self.datas:
            aliases = self._required_input_fields.get(id(data))
            if not aliases:
                continue
            metadata = _alignment_metadata(data)
            if not isinstance(metadata, Mapping):
                # Preserve the historical behavior of raw, non-aligned feeds;
                # they do not carry the per-field history needed by this gate.
                continue
            present = metadata.get("present")
            if present is not None and (
                np.asarray(present).ndim != 1 or len(present) != len(self._grid)
            ):
                raise DatasetError(
                    "factor source presence mask length does not match the research grid"
                )
            fields = metadata.get("field_present") or {}
            validated_times = False
            for alias in aliases:
                # PandasData can map the line to a differently named column
                # (including case-insensitive automatic selection).
                field = alias
                mapping = getattr(data, "_colmapping", None)
                if isinstance(mapping, Mapping) and alias in mapping:
                    column = mapping[alias]
                    if isinstance(column, int):
                        columns = getattr(getattr(data.p, "dataname", None), "columns", ())
                        field = str(columns[column]) if 0 <= column < len(columns) else None
                    else:
                        field = str(column) if column is not None else None
                values = fields.get(field)
                if values is None:
                    # A custom feed can expose a computed line absent from its
                    # source-frame metadata. Preserve the existing fallback;
                    # this path cannot prove that line's historical window.
                    continue
                if not validated_times:
                    self._validate_source_close_times(data, metadata, expected_times)
                    validated_times = True
                if np.asarray(values).ndim != 1 or len(values) != len(self._grid):
                    raise DatasetError(
                        "factor source field mask length does not match the research grid"
                    )
                counts[(id(data), alias)] = _cumulative(values, np)
        return counts

    def _validate_source_close_times(
        self, data: Any, metadata: Mapping, expected_times: Any
    ) -> None:
        """Validate positional masks against close time, independently of open time."""
        frame = cast(Any, getattr(data.p, "dataname", None))
        time_values = getattr(frame, "index", None)
        if callable(time_values):
            time_values = None
        if getattr(data.p, "datetime", None) is not None:
            mapping = getattr(data, "_colmapping", None)
            column = mapping.get("datetime") if isinstance(mapping, Mapping) else None
            if isinstance(column, int) and hasattr(frame, "iloc"):
                time_values = frame.iloc[:, column]
            elif isinstance(column, str):
                try:
                    time_values = frame[column]
                except (KeyError, TypeError):
                    time_values = None
            else:
                time_values = None
        if time_values is None:
            # An intact alignment marker is sufficient when a custom feed
            # does not expose its source index. Unrelated grid hashes are not.
            if metadata.get("grid_sha256") == self._research.grid_sha256:
                return
            raise DatasetError("factor source close-time alignment cannot be established")
        # Compare backtrader's UTC day numbers only (G7): date2num normalizes an
        # aware time to UTC, so one instant always gives one number, and no
        # per-value num2date conversion is needed for a one-time check.
        try:
            tzinput = getattr(data, "_tzinput", None)
            source_numbers = []
            for value in time_values:
                when = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
                if tzinput:
                    # As before: the source wall clock (an aware value's UTC
                    # wall clock) is read as tzinput local time.
                    if getattr(when, "tzinfo", None) is not None:
                        when = when.astimezone(timezone.utc).replace(tzinfo=None)
                    when = tzinput.localize(when)
                source_numbers.append(date2num(when))
            expected_numbers = [
                date2num(item.to_pydatetime() if hasattr(item, "to_pydatetime") else item)
                for item in expected_times
            ]
        except (AttributeError, TypeError, ValueError, OverflowError) as exc:
            raise DatasetError("factor source close-time alignment cannot be established") from exc
        if source_numbers != expected_numbers:
            raise DatasetError(
                "factor source close-time alignment does not match the research grid"
            )

    def _validate_preloaded_named_source_clocks(self) -> None:
        """Reject a filtered named input before once-mode can read shifted rows."""
        if not bool(getattr(getattr(self, "env", None), "_dopreload", False)):
            return
        expected_numbers = self._research._feed_datetime_nums
        for data in self._named_source_datas:
            line = data.datetime
            # A raw source may include later bars outside the research window;
            # only the calculation-grid prefix is consumed by this strategy.
            if line.buflen() < len(self._grid):
                raise DatasetError(
                    "factor source actual close clock length does not match the research grid"
                )
            for position, expected_number in enumerate(expected_numbers):
                try:
                    number = float(line.array[position])
                    if number == expected_number:
                        continue
                    actual = num2date(number, tz=timezone.utc, naive=False)
                except (IndexError, TypeError, ValueError, OverflowError) as exc:
                    raise DatasetError(
                        "factor source actual close clock cannot be established"
                    ) from exc
                if actual != self._grid[position]:
                    raise DatasetError(
                        "factor source actual close clock does not match the research grid"
                    )

    @staticmethod
    def _current_feed_time(
        data: Any,
        current_num: Optional[float] = None,
        current: Optional[datetime] = None,
    ) -> Optional[datetime]:
        try:
            feed_num = float(data.datetime[0])
            if current is not None and current_num is not None and feed_num == current_num:
                return current
            return cast(datetime, num2date(feed_num, tz=timezone.utc, naive=False))
        except (IndexError, TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _feed_present(data: Any, index: int) -> bool:
        metadata = _alignment_metadata(data)
        if metadata is None:
            return True
        present = metadata.get("present", ())
        return index < len(present) and bool(present[index])

    @staticmethod
    def _line_value(data: Any, line_name: str) -> float:
        try:
            value = float(getattr(data, line_name)[0])
        except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
            return float("nan")
        return value if math.isfinite(value) else float("nan")

    # -- finalization ----------------------------------------------------

    def _panel_context(self) -> Any:
        if self._panel_context_cache is not None:
            return self._panel_context_cache
        from ..research.sink import PanelContext

        pd = require_research_runtime()
        grid = self._research.grid
        targets = tuple(self._research.targets)
        opens: Dict[str, Any] = {}
        closes: Dict[str, Any] = {}
        complete = True
        for asset, data in zip(targets, self._target_datas):
            metadata = _alignment_metadata(data)
            values = metadata.get("prices_open") if isinstance(metadata, Mapping) else None
            if values is None or len(values) != len(grid):
                complete = False
                break
            opens[asset] = values
            closes[asset] = cast(Mapping[str, Any], metadata)["prices_close"]
        prices_open = pd.DataFrame(opens, index=grid.index) if complete else None
        prices_close = pd.DataFrame(closes, index=grid.index) if complete else None
        study_index = grid.index[
            (grid.index >= self._research.start) & (grid.index <= self._research.end)
        ]
        universe = self._research.universe.unstack("asset")
        universe.index = pd.DatetimeIndex(study_index, name="close_time", freq=None)
        universe = universe.reindex(index=study_index, columns=list(targets))
        self._panel_context_cache = PanelContext(
            grid=grid,
            start=self._research.start,
            end=self._research.end,
            target_order=targets,
            factor_order=tuple(self._factor_specs_by_name),
            directions={name: spec.direction for name, spec in self._factor_specs_by_name.items()},
            universe=universe,
            groups=self._research.groups,
            prices_open=prices_open,
            prices_close=prices_close,
        )
        return self._panel_context_cache

    def get_panel(self) -> Any:
        """Return the finalized panel; repeated calls return the same object."""
        if self._panel is None:
            raise RuntimeError("panel is unavailable before the full grid has run")
        return self._panel

    def stop(self) -> None:
        # Cerebro calls _stop() while unwinding a failing run. Do not replace a
        # useful factor callback exception with a secondary partial-grid error.
        failed = (
            self._collection_failed
            or sys.exc_info()[0] is not None
            or bool(getattr(getattr(self, "cerebro", None), "_factor_research_run_failed", False))
            or any(
                bool(getattr(getattr(instance, "_factor_strict_context", None), "failed", False))
                for instances in self._factor_instances_by_name.values()
                for instance in instances
            )
        )
        try:
            if failed:
                return
            if self._grid_cursor != len(self._grid):
                raise RuntimeError("FactorStrategy did not sample every ResearchSpec grid point")
            graphs = self._validate_research_ownership()
            for name, instances in self._factor_instances_by_name.items():
                for factor in instances:
                    for nested in graphs[id(factor)]:
                        if not nested.lifecycle_diagnostics["coverage_matches"]:
                            raise RuntimeError(
                                "factor %s did not cover every calculation-grid point" % name
                            )
            from ..research.sink import CsvSink, MemorySink

            if self._defer_csv_publication and type(self._sink) is CsvSink:
                self._panel = MemorySink.finalize(self._sink, self._panel_context())
                self._pending_csv_panel = self._panel
            else:
                self._panel = self._sink.finalize(self._panel_context())
        finally:
            if failed or sys.exc_info()[0] is not None:
                # Preserve the original run failure if cleanup itself fails.
                try:
                    self._sink.close()
                except BaseException:
                    pass
            else:
                self._sink.close()

    def _defer_research_csv(self) -> None:
        """Defer only the built-in CSV sink while Cerebro tears down a run."""
        from ..research.sink import CsvSink

        self._defer_csv_publication = type(self._sink) is CsvSink

    def _commit_research_csv(self) -> None:
        panel = self._pending_csv_panel
        if panel is not None:
            self._sink.write(panel)
            self._pending_csv_panel = None
        self._defer_csv_publication = False

    @staticmethod
    def _freeze_factor_graph(
        root: FactorIndicator,
    ) -> Tuple[Tuple[FactorIndicator, ...], Tuple[Tuple[Any, Any], ...]]:
        """Freeze every scheduled child edge below this offline factor."""
        nodes: List[FactorIndicator] = []
        edges: List[Tuple[Any, Any]] = []
        active = set()
        visited: Dict[int, bool] = {}

        def visit(node: Any) -> bool:
            identity = id(node)
            if identity in active:
                raise RuntimeError("research factor graph has cyclic nodes")
            if identity in visited:
                return visited[identity]
            active.add(identity)
            is_factor = isinstance(node, FactorIndicator)
            if is_factor:
                nodes.append(node)
            relevant = is_factor
            for children in getattr(node, "_lineiterators", {}).values():
                for child in children:
                    child_relevant = visit(child)
                    edges.append((node, child))
                    relevant = relevant or child_relevant
            active.remove(identity)
            visited[identity] = relevant
            return relevant

        visit(root)
        graph = (tuple(nodes), tuple(edges))
        FactorStrategy._check_factor_edges(graph[1])
        return graph

    @staticmethod
    def _check_factor_edges(edges: Tuple[Tuple[Any, Any], ...]) -> None:
        counts_by_parent_and_type = {}
        for parent, child in edges:
            key = (id(parent), child._ltype)
            if key not in counts_by_parent_and_type:
                children = getattr(parent, "_lineiterators", {}).get(child._ltype, ())
                counts_by_parent_and_type[key] = Counter(id(item) for item in children)
            if child._owner is not parent or counts_by_parent_and_type[key][id(child)] != 1:
                raise RuntimeError("research factor graph changed during collection")

    def _validate_factor_graph(
        self, root: FactorIndicator, host_counts: Counter[int]
    ) -> Tuple[FactorIndicator, ...]:
        nodes, edges = self._factor_graphs[id(root)]
        if (
            root._owner is not self
            or host_counts[id(root)] != 1
            or any(host_counts[id(child)] for _, child in edges)
        ):
            raise RuntimeError("research factor graph changed during collection")
        current_nodes, current_edges = self._freeze_factor_graph(root)
        if Counter(map(id, nodes)) != Counter(map(id, current_nodes)) or Counter(
            (id(parent), id(child)) for parent, child in edges
        ) != Counter((id(parent), id(child)) for parent, child in current_edges):
            raise RuntimeError("research factor graph changed during collection")
        return nodes

    def _validate_research_ownership(self) -> Dict[int, Tuple[FactorIndicator, ...]]:
        """Require each protected graph node to have its one expected driver."""
        expected_parents = {}
        graphs: Dict[int, Tuple[FactorIndicator, ...]] = {}
        host_counts = Counter(id(item) for item in self._lineiterators[LineIterator.IndType])
        for instances in self._factor_instances_by_name.values():
            for root in instances:
                if root._owner is not self or host_counts[id(root)] != 1:
                    raise RuntimeError("research factor is missing from its owner graph")
                graphs[id(root)] = self._validate_factor_graph(root, host_counts)
                for parent, child in ((self, root),) + self._factor_graphs[id(root)][1]:
                    child_id = id(child)
                    if child_id in expected_parents:
                        raise RuntimeError("research factor graph has multiple scheduling paths")
                    expected_parents[child_id] = id(parent)

        observed: Counter[int] = Counter()
        strategies = tuple(getattr(getattr(self, "cerebro", None), "runningstrats", ()))
        if not any(strategy is self for strategy in strategies):
            strategies += (self,)
        for strategy in strategies:
            visited = set()
            pending = [strategy]
            while pending:
                parent = pending.pop()
                parent_id = id(parent)
                if parent_id in visited:
                    continue
                visited.add(parent_id)
                for children in getattr(parent, "_lineiterators", {}).values():
                    for child in children:
                        child_id = id(child)
                        if child_id in expected_parents:
                            if expected_parents[child_id] != parent_id:
                                raise RuntimeError(
                                    "research factor graph has multiple scheduling paths"
                                )
                            observed[child_id] += 1
                        pending.append(child)
        if any(observed[child_id] != 1 for child_id in expected_parents):
            raise RuntimeError("research factor graph has multiple scheduling paths")
        return graphs

    @staticmethod
    def _factor_tree(root: FactorIndicator) -> Tuple[FactorIndicator, ...]:
        result: List[FactorIndicator] = []
        seen = set()

        def visit(node: Any) -> None:
            if id(node) in seen:
                return
            seen.add(id(node))
            if isinstance(node, FactorIndicator):
                result.append(node)
            for children in getattr(node, "_lineiterators", {}).values():
                for child in children:
                    visit(child)

        visit(root)
        return tuple(result)

    def evaluate(self, spec: Any = None, **kwargs: Any) -> Any:
        """Evaluate the collected panel through the public research adapter."""
        from ..research.fincore_adapter import evaluate_frames

        if spec is not None and kwargs:
            raise ResearchConfigError("pass either spec or evaluation keyword arguments, not both")
        if spec is None and kwargs:
            spec = kwargs
        return evaluate_frames(self.get_panel(), spec)


def _cumulative(values: Any, np: Any) -> Any:
    array = np.asarray(values, dtype=np.int64)
    return np.concatenate(([0], np.cumsum(array)))


def _input_sources(spec: FactorSpec) -> Tuple[Tuple[str, str], ...]:
    """Map declared formula fields to their qualified feed and column."""
    bindings = spec.field_bindings
    sources: List[Tuple[str, str]] = []
    for alias in tuple(getattr(spec.indicator, "formula_fields", ())):
        binding = bindings.get(alias)
        sources.extend(_source_aliases(alias, binding, bindings))
    return tuple(dict.fromkeys(sources))


def _source_aliases(alias: str, binding: Any, bindings: Mapping) -> List[Tuple[str, str]]:
    if isinstance(binding, Mapping):
        derive = binding.get("derive")
        if derive == "adv":
            source = binding.get("source")
            return _source_aliases(source, bindings.get(source), bindings) if source else []
        if derive == "vwap_volume":
            output: List[Tuple[str, str]] = []
            for source in (binding.get("vwap"), binding.get("volume")):
                if source:
                    output.extend(_source_aliases(source, bindings.get(source), bindings))
            return output
        binding = binding.get("source")
    if not isinstance(binding, str) or not binding.startswith("feed:"):
        return []
    parts = binding.split(":")
    if len(parts) != 3:
        return []
    return [(parts[1], parts[2])]


def _alignment_metadata(data: Any) -> Optional[Mapping]:
    metadata = getattr(data, _ALIGNMENT_V2, None)
    if isinstance(metadata, Mapping):
        return metadata
    metadata = getattr(data, _ALIGNMENT_V1, None)
    return metadata if isinstance(metadata, Mapping) else None


__all__ = ("FactorStrategy",)
