"""Native Backtrader strategy that collects a plain-frame research panel."""

from __future__ import annotations

import math
import sys
import types
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

from .. import Strategy
from ..utils import date2num, num2date
from ..errors import ResearchConfigError, DatasetError
from ..lineiterator import LineIterator
from ..lineseries import LineSeries
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
_EMPTY_LINEITERATORS = types.MappingProxyType({})
_IND_TYPE = LineIterator.IndType
_STRAT_TYPE = LineIterator.StratType
_OBS_TYPE = LineIterator.ObsType
_STANDARD_BUCKETS = frozenset((_IND_TYPE, _STRAT_TYPE, _OBS_TYPE))
_DICT_GET = dict.get
_STANDARD_LINE_GETATTR = LineSeries.__dict__["__getattr__"]
_TYPE_MRO_GET = type.__dict__["__mro__"].__get__
_TYPE_DICT_GET = type.__dict__["__dict__"].__get__
_FACTOR_HOST_FIELDS = (
    "cerebro", "_lineiterators", "_factor_instances_by_name", "_factor_graphs",
    "_factor_validation_roots", "_factor_validation_parents", "_factor_validation_objects",
    "_factor_validation_duplicate_parent", "_factor_validation_root_by_id",
    "_factor_validation_graphs", "_factor_validation_expected_parents",
    "_factor_validation_nested_ids", "_factor_validation_child_counts",
    "_factor_validation_host_counts", "_factor_validation_observed",
    "_factor_validation_visited", "_factor_validation_pending", "_factor_validation_fast_plan",
)


class _FactorValidationFastPlan:
    """Flat identity snapshot built after a passing full graph check.

    Subsequent per-bar validations verify live object/type/owner/edge
    identities directly against these flat tuples. Any
    discrepancy invalidates the snapshot and falls back to full validation.
    """

    __slots__ = (
        "cerebro",
        "strategies",
        "by_name_items",
        "graph_items",
        "factor_objects",
        "validation_inputs",
        "plain_types",
        "standard_leaf_nodes",
        "branch_nodes",
        "external_leaf_nodes",
        "external_branch_nodes",
    )

    def __init__(
        self,
        cerebro: Any,
        strategies: Tuple[Any, ...],
        by_name_items: Tuple[Tuple[str, Tuple[FactorIndicator, ...]], ...],
        graph_items: Tuple[Tuple[int, Any], ...],
        factor_objects: Tuple[Tuple[Any, bool], ...],
        validation_inputs: Any,
        plain_types: Tuple[type, ...],
        standard_leaf_nodes: Tuple[Tuple[Any, type, Any, Any], ...],
        branch_nodes: Tuple[
            Tuple[
                Any,
                type,
                Any,
                Any,
                Tuple[Tuple[Any, Tuple[Any, ...]], ...],
            ],
            ...,
        ],
        external_leaf_nodes: Tuple[Tuple[Any, type, Any], ...],
        external_branch_nodes: Tuple[
            Tuple[Any, type, Any, Tuple[Tuple[Any, Tuple[Any, ...]], ...]], ...
        ],
    ) -> None:
        self.cerebro = cerebro
        self.strategies = strategies
        self.by_name_items = by_name_items
        self.graph_items = graph_items
        self.factor_objects = factor_objects
        self.validation_inputs = validation_inputs
        self.plain_types = plain_types
        self.standard_leaf_nodes = standard_leaf_nodes
        self.branch_nodes = branch_nodes
        self.external_leaf_nodes = external_leaf_nodes
        self.external_branch_nodes = external_branch_nodes


def _factor_validation_plain_access(
    node_type: type, fields: Tuple[str, ...] = ("_owner", "_ltype", "_lineiterators")
) -> bool:
    """Exclude custom accessors whose calls may have observable side effects."""
    # Calling type.__getattribute__ directly is insufficient: a metaclass can
    # still supply a data descriptor for these names.  Invoke type's own
    # getset descriptors, then inspect only the resulting static namespaces.
    mro = _TYPE_MRO_GET(node_type, type(node_type))
    for base in mro:
        if any(type(key) is not str for key in _TYPE_DICT_GET(base, type(base))):
            return False
    for base in mro:
        namespace = _TYPE_DICT_GET(base, type(base))
        if "__getattribute__" in namespace:
            if namespace["__getattribute__"] is not object.__getattribute__:
                return False
            break
    else:
        return False
    for base in mro:
        namespace = _TYPE_DICT_GET(base, type(base))
        if "__getattr__" in namespace:
            if namespace["__getattr__"] is not _STANDARD_LINE_GETATTR:
                return False
            break
    for base in mro:
        namespace = _TYPE_DICT_GET(base, type(base))
        if "__dict__" in namespace:
            if type(namespace["__dict__"]) is not types.GetSetDescriptorType:
                return False
            break
    else:
        return False
    for name in fields + ("__class__",):
        for base in mro:
            namespace = _TYPE_DICT_GET(base, type(base))
            if name not in namespace:
                continue
            value = namespace[name]
            if name == "__class__" and base is object:
                break
            # Inspect the descriptor type without invoking its metaclass's
            # potentially stateful or failing __getattribute__.
            value_type = type(value)
            for descriptor_base in _TYPE_MRO_GET(value_type, type(value_type)):
                descriptor_namespace = _TYPE_DICT_GET(descriptor_base, type(descriptor_base))
                if any(type(key) is not str for key in descriptor_namespace):
                    return False
                if "__get__" in descriptor_namespace:
                    return False
            break
    return True


def _factor_validation_plain_host(host: Any, fields: Tuple[str, ...]) -> bool:
    if not _factor_validation_plain_access(type(host), fields):
        return False
    state = object.__getattribute__(host, "__dict__")
    return (
        type(state) is dict
        and all(type(key) is str for key in state)
        and all(field in state for field in fields)
    )


def _factor_validation_plain_fields(node: Any, *, owner: bool) -> bool:
    """Check field presence without invoking __getattr__ or descriptors."""
    fields = object.__getattribute__(node, "__dict__")
    if (
        type(fields) is not dict
        or any(type(key) is not str for key in fields)
        or "_lineiterators" not in fields
    ):
        return False
    if owner and "_owner" not in fields:
        return False
    if owner and "_ltype" not in fields:
        node_type = type(node)
        for base in _TYPE_MRO_GET(node_type, type(node_type)):
            if "_ltype" in _TYPE_DICT_GET(base, type(base)):
                break
        else:
            return False
    return True


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
        grouped_sources = {
            name: tuple((group, item[source_key]) for group, item in by_group.items())
            for name, source_key in (
                ("call_times", "call_times_source"),
                ("next_times", "next_times_source"),
                ("once_ranges", "once_ranges_source"),
                ("once_times", "once_times_source"),
                ("coverage_times", "coverage_times_source"),
            )
        }
        grouped_truncation = {
            name: tuple((group, item[flag_key]) for group, item in by_group.items())
            for name, flag_key in (
                ("call_times", "call_times_truncated"),
                ("next_times", "next_times_truncated"),
                ("once_ranges", "once_ranges_truncated"),
                ("once_times", "once_times_truncated"),
                ("coverage_times", "coverage_times_truncated"),
            )
        }
        truncation_summary = {
            name: any(truncated for _group, truncated in flags)
            for name, flags in grouped_truncation.items()
        }
        return {
            "diagnostic_kind": "grouped_lifecycle_samples",
            "sample_limit_by_group": tuple(
                (group, item["sample_limit"]) for group, item in by_group.items()
            ),
            "full_trace_captured": bool(by_group)
            and all(
                item["diagnostic_kind"] == "captured_offline_trace"
                for item in by_group.values()
            ),
            "samples_complete": not any(truncation_summary.values()),
            "call_count": sum(item["call_count"] for item in by_group.values()),
            "call_times": tuple((group, item["call_times"]) for group, item in by_group.items()),
            "call_times_source": "per_group_actual_samples",
            "call_times_source_by_group": grouped_sources["call_times"],
            "call_times_truncated": truncation_summary["call_times"],
            "call_times_truncated_by_group": grouped_truncation["call_times"],
            "grid_count": max((item["grid_count"] for item in by_group.values()), default=0),
            "grid_matches": bool(by_group)
            and all(item["grid_matches"] for item in by_group.values()),
            "next_count": sum(item["next_count"] for item in by_group.values()),
            "next_times": tuple((group, item["next_times"]) for group, item in by_group.items()),
            "next_times_source": "per_group_actual_samples",
            "next_times_source_by_group": grouped_sources["next_times"],
            "next_times_truncated": truncation_summary["next_times"],
            "next_times_truncated_by_group": grouped_truncation["next_times"],
            "once_ranges": tuple((group, item["once_ranges"]) for group, item in by_group.items()),
            "once_ranges_source": "per_group_actual_ranges",
            "once_ranges_source_by_group": grouped_sources["once_ranges"],
            "once_ranges_truncated": truncation_summary["once_ranges"],
            "once_ranges_truncated_by_group": grouped_truncation["once_ranges"],
            "once_range_count": sum(item["once_range_count"] for item in by_group.values()),
            "once_count": sum(item["once_count"] for item in by_group.values()),
            "once_times": tuple((group, item["once_times"]) for group, item in by_group.items()),
            "once_times_source": "per_group_diagnostics",
            "once_times_source_by_group": grouped_sources["once_times"],
            "once_times_truncated": truncation_summary["once_times"],
            "once_times_truncated_by_group": grouped_truncation["once_times"],
            "coverage_count": sum(item["coverage_count"] for item in by_group.values()),
            "coverage_times": tuple(
                (group, item["coverage_times"]) for group, item in by_group.items()
            ),
            "coverage_times_source": "per_group_diagnostics",
            "coverage_times_source_by_group": grouped_sources["coverage_times"],
            "coverage_times_truncated": truncation_summary["coverage_times"],
            "coverage_times_truncated_by_group": grouped_truncation["coverage_times"],
            "coverage_matches": bool(by_group)
            and all(item["coverage_matches"] for item in by_group.values()),
            "expected_call_count": sum(item["expected_call_count"] for item in by_group.values()),
            "expected_call_times_sample": tuple(
                (group, item["expected_call_times_sample"]) for group, item in by_group.items()
            ),
            "expected_call_times_sample_source": "per_group_validated_grid_samples",
            "expected_coverage_count": sum(
                item["expected_coverage_count"] for item in by_group.values()
            ),
            "expected_coverage_times_sample": tuple(
                (group, item["expected_coverage_times_sample"])
                for group, item in by_group.items()
            ),
            "expected_coverage_times_sample_source": "per_group_validated_grid_samples",
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
        self._factor_validation_parents: Tuple[
            Tuple[Any, Dict[int, Tuple[Any, int]], int], ...
        ] = ()
        self._factor_validation_roots: Tuple[FactorIndicator, ...] = ()
        self._factor_validation_root_by_id: Dict[int, FactorIndicator] = {}
        self._factor_validation_graphs: Dict[
            int, Tuple[Tuple[FactorIndicator, ...], Tuple[Tuple[Any, Any], ...]]
        ] = {}
        self._factor_validation_expected_parents: Dict[int, int] = {}
        self._factor_validation_nested_ids = set()
        self._factor_validation_duplicate_parent = False
        self._factor_validation_objects: Tuple[Tuple[Any, bool], ...] = ()
        self._factor_validation_lock = Lock()
        self._factor_validation_child_counts: Dict[int, int] = {}
        self._factor_validation_host_counts: Dict[int, int] = {}
        self._factor_validation_observed: Dict[int, int] = {}
        self._factor_validation_visited = set()
        self._factor_validation_pending: List[Any] = []
        self._factor_validation_fast_plan: Optional[_FactorValidationFastPlan] = None
        calculation_times: Optional[Tuple[datetime, ...]] = None
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
                if calculation_times is None:
                    calculation_times = self._calculation_times()
                instance._bind_grid(calculation_times)
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

        self._prepare_factor_graph_validation()

        if calculation_times is None:
            calculation_times = self._calculation_times()
        self._grid = calculation_times
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
        self._factor_validation_fast_plan = None
        try:
            super()._start()
            self._factor_validation_fast_plan = None
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
        self._validate_research_ownership()
        # Refuse to read or publish a row until every factor in its native
        # graph has actually computed this point (or its once range).
        for instances in self._factor_instances_by_name.values():
            for root in instances:
                for node in self._factor_graphs[id(root)][0]:
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
        """True when the declared lookback and its inputs are fully usable.

        The first eligible point needs ``lookback_h + 1`` bars.  A missing bar
        nulls its own grid point and the next ``lookback_h`` points, and a
        present bar whose declared input value is non-finite does the same.
        Per-field cumulative presence counts answer each query in constant
        time without rebuilding the deleted per-cell availability table.
        """
        lookback = spec.lookback_h
        if cursor < lookback:
            return False
        start = cursor - lookback
        expected = lookback + 1
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
            self._factor_validation_fast_plan = None
            self._validate_research_ownership()
            for name, instances in self._factor_instances_by_name.items():
                for factor in instances:
                    for nested in self._factor_graphs[id(factor)][0]:
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

    def _prepare_factor_graph_validation(self) -> None:
        """Index the frozen graph once; later checks still inspect every live edge."""
        roots: List[FactorIndicator] = []
        root_by_id: Dict[int, FactorIndicator] = {}
        graphs: Dict[int, Tuple[Tuple[FactorIndicator, ...], Tuple[Tuple[Any, Any], ...]]] = {}
        expected_parents: Dict[int, int] = {}
        nested_ids = set()
        parent_children: Dict[
            int, Tuple[Any, Dict[int, Tuple[Any, int]], int]
        ] = {}
        objects: Dict[int, Tuple[Any, bool]] = {}
        duplicate_parent = False

        def remember_parent(node: Any) -> None:
            identity = id(node)
            if identity not in parent_children:
                parent_children[identity] = (node, {}, 0)
            remember_object(node)

        def remember_object(node: Any) -> None:
            identity = id(node)
            if identity not in objects:
                objects[identity] = (node, isinstance(node, FactorIndicator))

        for instances in self._factor_instances_by_name.values():
            for root in instances:
                roots.append(root)
                root_by_id[id(root)] = root
                graphs[id(root)] = self._factor_graphs[id(root)]
                remember_parent(root)
                if id(root) in expected_parents:
                    duplicate_parent = True
                else:
                    expected_parents[id(root)] = id(self)
                for parent, child in self._factor_graphs[id(root)][1]:
                    remember_parent(parent)
                    remember_parent(child)
                    parent_id = id(parent)
                    child_id = id(child)
                    record = parent_children[parent_id]
                    counts = record[1]
                    prior = counts.get(child_id)
                    if prior is None:
                        counts[child_id] = (child._ltype, 1)
                    else:
                        counts[child_id] = (prior[0], prior[1] + 1)
                    parent_children[parent_id] = (parent, counts, record[2] + 1)
                    if child_id in expected_parents:
                        duplicate_parent = True
                    else:
                        expected_parents[child_id] = parent_id
                    nested_ids.add(child_id)

        self._factor_validation_roots = tuple(roots)
        self._factor_validation_root_by_id = root_by_id
        self._factor_validation_graphs = graphs
        self._factor_validation_expected_parents = expected_parents
        self._factor_validation_nested_ids = nested_ids
        self._factor_validation_parents = tuple(parent_children.values())
        self._factor_validation_duplicate_parent = duplicate_parent
        self._factor_validation_objects = tuple(objects.values())
        self._factor_validation_fast_plan = None

    def _build_factor_validation_fast_plan(
        self, cerebro: Any, strategies: Tuple[Any, ...]
    ) -> Optional[_FactorValidationFastPlan]:
        """Build a flat O(V) identity verification snapshot from a just-validated graph."""
        if not _factor_validation_plain_host(self, _FACTOR_HOST_FIELDS):
            return None
        if cerebro is not None and not _factor_validation_plain_host(cerebro, ("runningstrats",)):
            return None
        by_name = self._factor_instances_by_name
        if type(by_name) is not dict:
            return None
        by_name_items: List[Tuple[str, Tuple[FactorIndicator, ...]]] = []
        for name, instances in by_name.items():
            if type(instances) is not tuple:
                return None
            by_name_items.append((name, instances))

        graphs = self._factor_graphs
        if type(graphs) is not dict or any(type(key) is not int for key in graphs):
            return None
        graph_items = tuple((id(root), graphs[id(root)]) for root in self._factor_validation_roots)

        # Full validation uses isinstance on each object.  A node can expose
        # a dynamic __class__, so grouping by type and using issubclass loses
        # information even when the node's actual type never changes.
        factor_objects = self._factor_validation_objects
        roots = self._factor_validation_roots
        parents = self._factor_validation_parents
        root_index = self._factor_validation_root_by_id
        graph_index = self._factor_validation_graphs
        parent_index = self._factor_validation_expected_parents
        nested_ids = self._factor_validation_nested_ids
        if (
            type(roots) is not tuple
            or type(parents) is not tuple
            or type(factor_objects) is not tuple
            or any(type(index) is not dict for index in (root_index, graph_index, parent_index))
            or type(nested_ids) is not set
        ):
            return None
        if (
            any(type(key) is not int for index in (root_index, graph_index, parent_index) for key in index)
            or any(type(value) is not int for value in parent_index.values())
            or any(type(key) is not int for key in nested_ids)
        ):
            return None
        child_indexes = []
        for _parent, children, _edge_count in parents:
            if (
                type(children) is not dict
                or any(type(key) is not int for key in children)
                or any(
                    type(value) is not tuple
                    or len(value) != 2
                    or type(value[0]) is not int
                    or type(value[1]) is not int
                    for value in children.values()
                )
            ):
                return None
            child_indexes.append((children, tuple(children.items())))
        validation_inputs = (
            roots,
            parents,
            factor_objects,
            self._factor_validation_duplicate_parent,
            (root_index, tuple(root_index.items())),
            (graph_index, tuple(graph_index.items())),
            (parent_index, tuple(parent_index.items())),
            (nested_ids, frozenset(nested_ids)),
            tuple(child_indexes),
        )

        expected_parents = self._factor_validation_expected_parents
        standard_leaf_nodes: List[Tuple[Any, type, Any, Any]] = []
        branch_nodes: List[
            Tuple[
                Any,
                type,
                Any,
                Any,
                Tuple[Tuple[Any, Tuple[Any, ...]], ...],
            ]
        ] = []
        plain_types = []
        for parent, _expected_children, expected_edge_count in self._factor_validation_parents:
            node_type = type(parent)
            if not _factor_validation_plain_access(node_type):
                return None
            if not _factor_validation_plain_fields(parent, owner=True):
                return None
            if not any(previous is node_type for previous in plain_types):
                plain_types.append(node_type)
            try:
                owner = parent._owner
                li = parent._lineiterators
            except AttributeError:
                return None
            li_type = type(li)
            if li_type is not defaultdict and li_type is not dict:
                return None
            if any(type(key) is not int for key in li):
                return None
            if expected_edge_count == 0:
                if any(
                    key not in _STANDARD_BUCKETS or type(children) is not list or children
                    for key, children in li.items()
                ):
                    return None
                standard_leaf_nodes.append((parent, node_type, owner, li))
                continue
            nonempty_buckets: List[Tuple[Any, Tuple[Any, ...]]] = []
            for key, children in li.items():
                if type(children) is not list:
                    return None
                if children:
                    nonempty_buckets.append((key, tuple(children)))
                elif key not in _STANDARD_BUCKETS:
                    return None
            branch_nodes.append(
                (parent, node_type, owner, li, tuple(nonempty_buckets))
            )

        # Capture every non-factor node reachable from every active strategy
        # (including self, observers, and sibling strategies) so any late
        # cross-strategy hijack or host mutation invalidates the fast path.
        external_leaf_nodes: List[Tuple[Any, type, Any]] = []
        external_branch_nodes: List[
            Tuple[Any, type, Any, Tuple[Tuple[Any, Tuple[Any, ...]], ...]]
        ] = []
        walk_roots = list(strategies)
        if not any(item is self for item in walk_roots):
            walk_roots.append(self)
        ext_seen = set()
        ext_pending = list(walk_roots)
        while ext_pending:
            node = ext_pending.pop()
            node_id = id(node)
            if node_id in ext_seen or node_id in expected_parents:
                continue
            ext_seen.add(node_id)
            node_type = type(node)
            if not _factor_validation_plain_access(node_type):
                return None
            if not _factor_validation_plain_fields(node, owner=False):
                return None
            if not any(previous is node_type for previous in plain_types):
                plain_types.append(node_type)
            try:
                li = node._lineiterators
            except AttributeError:
                return None
            li_type = type(li)
            if li_type is not defaultdict and li_type is not dict:
                return None
            if any(type(key) is not int for key in li):
                return None
            nonempty_buckets = []
            for key, children in li.items():
                if type(children) is not list:
                    return None
                if children:
                    children_tuple = tuple(children)
                    nonempty_buckets.append((key, children_tuple))
                    for child in children_tuple:
                        child_id = id(child)
                        if child_id not in ext_seen and child_id not in expected_parents:
                            ext_pending.append(child)
                elif key not in _STANDARD_BUCKETS:
                    return None
            if not nonempty_buckets:
                external_leaf_nodes.append((node, node_type, li))
            else:
                external_branch_nodes.append((node, node_type, li, tuple(nonempty_buckets)))

        return _FactorValidationFastPlan(
            cerebro=cerebro,
            strategies=strategies,
            by_name_items=tuple(by_name_items),
            graph_items=graph_items,
            factor_objects=factor_objects,
            validation_inputs=validation_inputs,
            plain_types=tuple(plain_types),
            standard_leaf_nodes=tuple(standard_leaf_nodes),
            branch_nodes=tuple(branch_nodes),
            external_leaf_nodes=tuple(external_leaf_nodes),
            external_branch_nodes=tuple(external_branch_nodes),
        )

    def _check_factor_validation_fast_plan(self, plan: _FactorValidationFastPlan) -> bool:
        """Verify live object, owner, edge, and index snapshots."""
        try:
            if not _factor_validation_plain_host(self, _FACTOR_HOST_FIELDS):
                return False
            if plan.cerebro is not None and not _factor_validation_plain_host(
                plan.cerebro, ("runningstrats",)
            ):
                return False
            for node_type in plan.plain_types:
                if not _factor_validation_plain_access(node_type):
                    return False
            # Check all fields before reading any of them.  Otherwise a
            # missing field can invoke __getattr__ in the fast path and then
            # invoke it a second time in the full fallback with a new result.
            for node, node_type, _owner, _li in plan.standard_leaf_nodes:
                if (type(node) is not node_type or not _factor_validation_plain_fields(node, owner=True)
                        or any(type(key) is not int for key in _li)):
                    return False
            for node, node_type, _owner, _li, _children in plan.branch_nodes:
                if (type(node) is not node_type or not _factor_validation_plain_fields(node, owner=True)
                        or any(type(key) is not int for key in _li)):
                    return False
            for node, node_type, _li in plan.external_leaf_nodes:
                if (type(node) is not node_type or not _factor_validation_plain_fields(node, owner=False)
                        or any(type(key) is not int for key in _li)):
                    return False
            for node, node_type, _li, _children in plan.external_branch_nodes:
                if (type(node) is not node_type or not _factor_validation_plain_fields(node, owner=False)
                        or any(type(key) is not int for key in _li)):
                    return False
            cerebro = getattr(self, "cerebro", None)
            if cerebro is not plan.cerebro:
                return False
            if cerebro is not None:
                strategies = getattr(cerebro, "runningstrats", ())
                strategies_type = type(strategies)
                if (strategies_type is not list and strategies_type is not tuple) or len(
                    strategies
                ) != len(plan.strategies):
                    return False
                for live_strategy, expected_strategy in zip(strategies, plan.strategies):
                    if live_strategy is not expected_strategy:
                        return False

            by_name = self._factor_instances_by_name
            if type(by_name) is not dict or len(by_name) != len(plan.by_name_items):
                return False
            for (name, instances), (expected_name, expected_instances) in zip(
                by_name.items(), plan.by_name_items
            ):
                if name is not expected_name or instances is not expected_instances:
                    return False

            graphs = self._factor_graphs
            if type(graphs) is not dict or any(type(key) is not int for key in graphs):
                return False
            for root_id, expected_graph in plan.graph_items:
                if _DICT_GET(graphs, root_id) is not expected_graph:
                    return False

            (
                roots, parents, objects, duplicate_parent,
                root_index, graph_index, parent_index, nested_index, child_indexes,
            ) = plan.validation_inputs
            if (
                self._factor_validation_roots is not roots
                or self._factor_validation_parents is not parents
                or self._factor_validation_objects is not objects
                or self._factor_validation_duplicate_parent is not duplicate_parent
                or self._factor_validation_root_by_id is not root_index[0]
                or self._factor_validation_graphs is not graph_index[0]
                or self._factor_validation_expected_parents is not parent_index[0]
                or self._factor_validation_nested_ids is not nested_index[0]
            ):
                return False
            for index, items in (root_index, graph_index, parent_index):
                if len(index) != len(items) or any(type(key) is not int for key in index):
                    return False
                for key, value in items:
                    if _DICT_GET(index, key) is not value:
                        return False
            if (len(nested_index[0]) != len(nested_index[1])
                    or any(type(key) is not int for key in nested_index[0])):
                return False
            for node_id in nested_index[1]:
                if node_id not in nested_index[0]:
                    return False
            for index, items in child_indexes:
                if len(index) != len(items) or any(type(key) is not int for key in index):
                    return False
                for key, value in items:
                    if _DICT_GET(index, key) is not value:
                        return False
            for node, was_factor in plan.factor_objects:
                if isinstance(node, FactorIndicator) is not was_factor:
                    return False

            dict_get = _DICT_GET
            ind_type = _IND_TYPE
            obs_type = _OBS_TYPE
            standard_buckets = _STANDARD_BUCKETS
            list_type = list
            type_of = type
            len_of = len

            for (
                node,
                expected_type,
                expected_owner,
                expected_li,
            ) in plan.standard_leaf_nodes:
                if (
                    type_of(node) is not expected_type
                    or node._owner is not expected_owner
                    or node._lineiterators is not expected_li
                ):
                    return False
                li_len = len_of(expected_li)
                if li_len == 2:
                    c0 = dict_get(expected_li, ind_type)
                    c2 = dict_get(expected_li, obs_type)
                    if type_of(c0) is list_type and type_of(c2) is list_type:
                        if c0 or c2:
                            return False
                    else:
                        for key, children in expected_li.items():
                            if (
                                key not in standard_buckets
                                or type_of(children) is not list_type
                                or children
                            ):
                                return False
                elif li_len:
                    if li_len > 3:
                        return False
                    for key, children in expected_li.items():
                        if (
                            key not in standard_buckets
                            or type_of(children) is not list_type
                            or children
                        ):
                            return False

            for (
                node,
                expected_type,
                expected_owner,
                expected_li,
                nonempty_buckets,
            ) in plan.branch_nodes:
                if (
                    type_of(node) is not expected_type
                    or node._owner is not expected_owner
                ):
                    return False
                li = node._lineiterators
                if li is not expected_li:
                    return False
                matched_keys = 0
                for key, expected_children in nonempty_buckets:
                    live = dict_get(li, key)
                    if type_of(live) is not list_type or len_of(live) != len_of(expected_children):
                        return False
                    for live_child, expected_child in zip(live, expected_children):
                        if live_child is not expected_child:
                            return False
                        live_ltype = live_child._ltype
                        if type(live_ltype) is not int or live_ltype != key:
                            return False
                    matched_keys += 1
                li_len = len_of(li)
                if li_len != matched_keys:
                    if li_len > matched_keys + 3:
                        return False
                    for key, children in li.items():
                        if type_of(children) is not list_type:
                            return False
                        if children:
                            found = False
                            for expected_key, _ in nonempty_buckets:
                                if key == expected_key:
                                    found = True
                                    break
                            if not found:
                                return False
                        elif key not in standard_buckets:
                            return False

            for node, expected_type, expected_li in plan.external_leaf_nodes:
                if type_of(node) is not expected_type or node._lineiterators is not expected_li:
                    return False
                li_len = len_of(expected_li)
                if li_len == 2:
                    c0 = dict_get(expected_li, ind_type)
                    c2 = dict_get(expected_li, obs_type)
                    if type_of(c0) is list_type and type_of(c2) is list_type:
                        if c0 or c2:
                            return False
                    else:
                        for key, children in expected_li.items():
                            if (
                                key not in standard_buckets
                                or type_of(children) is not list_type
                                or children
                            ):
                                return False
                elif li_len:
                    if li_len > 3:
                        return False
                    for key, children in expected_li.items():
                        if (
                            key not in standard_buckets
                            or type_of(children) is not list_type
                            or children
                        ):
                            return False

            for node, expected_type, expected_li, nonempty_buckets in plan.external_branch_nodes:
                if type_of(node) is not expected_type:
                    return False
                li = node._lineiterators
                if li is not expected_li:
                    return False
                matched_keys = 0
                for key, expected_children in nonempty_buckets:
                    live = dict_get(li, key)
                    if type_of(live) is not list_type or len_of(live) != len_of(expected_children):
                        return False
                    for live_child, expected_child in zip(live, expected_children):
                        if live_child is not expected_child:
                            return False
                    matched_keys += 1
                li_len = len_of(li)
                if li_len != matched_keys:
                    if li_len > matched_keys + 3:
                        return False
                    for key, children in li.items():
                        if type_of(children) is not list_type:
                            return False
                        if children:
                            found = False
                            for expected_key, _ in nonempty_buckets:
                                if key == expected_key:
                                    found = True
                                    break
                            if not found:
                                return False
                        elif key not in standard_buckets:
                            return False

            return True
        except (AttributeError, KeyError, TypeError):
            return False

    def _validate_research_ownership(self) -> None:
        """Check live edges against a cached identity index on every call."""
        lock = self._factor_validation_lock
        if not lock.acquire(blocking=False):
            raise RuntimeError("research factor graph validation is already active")

        child_counts = self._factor_validation_child_counts
        host_counts = self._factor_validation_host_counts
        observed = self._factor_validation_observed
        visited = self._factor_validation_visited
        pending = self._factor_validation_pending

        try:
            root_count = 0
            duplicate_root = False
            for instances in self._factor_instances_by_name.values():
                for root in instances:
                    root_count += 1
                    root_id = id(root)
                    if (
                        self._factor_validation_root_by_id.get(root_id) is not root
                        or self._factor_graphs.get(root_id)
                        is not self._factor_validation_graphs.get(root_id)
                    ):
                        raise RuntimeError("research factor graph changed during collection")
                    root_occurrences = host_counts.get(root_id, 0) + 1
                    host_counts[root_id] = root_occurrences
                    duplicate_root = duplicate_root or root_occurrences > 1
            if duplicate_root:
                raise RuntimeError("research factor graph has multiple scheduling paths")
            if root_count != len(self._factor_validation_roots):
                raise RuntimeError("research factor is missing from its owner graph")
            host_counts.clear()

            host_indicators = self._lineiterators[LineIterator.IndType]
            root_by_id = self._factor_validation_root_by_id
            expected_parents = self._factor_validation_expected_parents
            nested_ids = self._factor_validation_nested_ids
            for item in host_indicators:
                item_id = id(item)
                if item_id in nested_ids:
                    raise RuntimeError("research factor graph changed during collection")
                if item_id in root_by_id:
                    host_counts[item_id] = host_counts.get(item_id, 0) + 1
                elif item_id in expected_parents:
                    raise RuntimeError("research factor graph changed during collection")
            for root in self._factor_validation_roots:
                if root._owner is not self or host_counts.get(id(root), 0) != 1:
                    raise RuntimeError("research factor is missing from its owner graph")

            for parent, expected_children, expected_edge_count in self._factor_validation_parents:
                lineiterators = getattr(parent, "_lineiterators", _EMPTY_LINEITERATORS)
                child_counts.clear()
                edge_count = 0

                for type_key, children in lineiterators.items():
                    for child in children:
                        child_id = id(child)
                        expected = expected_children.get(child_id)
                        if child._owner is not parent:
                            raise RuntimeError("research factor graph changed during collection")
                        if (
                            expected is None
                            or child._ltype != expected[0]
                            or type_key != expected[0]
                        ):
                            raise RuntimeError("research factor graph changed during collection")
                        expected_count = expected[1]
                        actual_count = child_counts.get(child_id, 0) + 1
                        if actual_count > expected_count:
                            raise RuntimeError("research factor graph changed during collection")
                        child_counts[child_id] = actual_count
                        edge_count += 1

                if edge_count != expected_edge_count:
                    raise RuntimeError("research factor graph changed during collection")

            for node, was_factor in self._factor_validation_objects:
                if isinstance(node, FactorIndicator) is not was_factor:
                    raise RuntimeError("research factor graph changed during collection")

            if self._factor_validation_duplicate_parent:
                raise RuntimeError("research factor graph has multiple scheduling paths")

            # Keep the full scheduler walk: another strategy can acquire a
            # protected node after initialization, and that must still fail.
            strategies = getattr(getattr(self, "cerebro", None), "runningstrats", ())
            found_self = False
            for strategy in strategies:
                if strategy is self:
                    found_self = True
                visited.clear()
                pending.clear()
                pending.append(strategy)
                while pending:
                    parent = pending.pop()
                    parent_id = id(parent)
                    if parent_id in visited:
                        continue
                    visited.add(parent_id)
                    for children in getattr(parent, "_lineiterators", _EMPTY_LINEITERATORS).values():
                        for child in children:
                            child_id = id(child)
                            if child_id in expected_parents:
                                if expected_parents[child_id] != parent_id:
                                    raise RuntimeError(
                                        "research factor graph has multiple scheduling paths"
                                    )
                                observed[child_id] = observed.get(child_id, 0) + 1
                            pending.append(child)
            if not found_self:
                visited.clear()
                pending.clear()
                pending.append(self)
                while pending:
                    parent = pending.pop()
                    parent_id = id(parent)
                    if parent_id in visited:
                        continue
                    visited.add(parent_id)
                    for children in getattr(parent, "_lineiterators", _EMPTY_LINEITERATORS).values():
                        for child in children:
                            child_id = id(child)
                            if child_id in expected_parents:
                                if expected_parents[child_id] != parent_id:
                                    raise RuntimeError(
                                        "research factor graph has multiple scheduling paths"
                                    )
                                observed[child_id] = observed.get(child_id, 0) + 1
                            pending.append(child)

            for child_id in expected_parents:
                if observed.get(child_id, 0) != 1:
                    raise RuntimeError("research factor graph has multiple scheduling paths")
        finally:
            try:
                child_counts.clear()
                host_counts.clear()
                observed.clear()
                visited.clear()
                pending.clear()
            finally:
                lock.release()

    def _validate_research_ownership_experimental(self) -> None:
        """Exercise the unaccepted fast plan explicitly; production uses the full check."""
        lock = self._factor_validation_lock
        if not lock.acquire(blocking=False):
            raise RuntimeError("research factor graph validation is already active")

        ran_full = False
        try:
            # The plan itself must not consume a stateful strategy accessor
            # before the full validator gets its first read.
            if not _factor_validation_plain_host(self, _FACTOR_HOST_FIELDS):
                ran_full = True
                self._validate_research_ownership_full()
                return
            plan = self._factor_validation_fast_plan
            if plan is not None and self._check_factor_validation_fast_plan(plan):
                return

            self._factor_validation_fast_plan = None
            ran_full = True
            cerebro, strategies = self._validate_research_ownership_full()
            self._factor_validation_fast_plan = self._build_factor_validation_fast_plan(
                cerebro, strategies
            )
        finally:
            try:
                if ran_full:
                    self._factor_validation_child_counts.clear()
                    self._factor_validation_host_counts.clear()
                    self._factor_validation_observed.clear()
                    self._factor_validation_visited.clear()
                    self._factor_validation_pending.clear()
            finally:
                lock.release()

    def _validate_research_ownership_full(self) -> Tuple[Any, Tuple[Any, ...]]:
        """Run the full edge, owner, type, and cross-strategy scheduler walk."""
        child_counts = self._factor_validation_child_counts
        host_counts = self._factor_validation_host_counts
        observed = self._factor_validation_observed
        visited = self._factor_validation_visited
        pending = self._factor_validation_pending

        root_count = 0
        duplicate_root = False
        for instances in self._factor_instances_by_name.values():
            for root in instances:
                root_count += 1
                root_id = id(root)
                if (
                    self._factor_validation_root_by_id.get(root_id) is not root
                    or self._factor_graphs.get(root_id)
                    is not self._factor_validation_graphs.get(root_id)
                ):
                    raise RuntimeError("research factor graph changed during collection")
                root_occurrences = host_counts.get(root_id, 0) + 1
                host_counts[root_id] = root_occurrences
                duplicate_root = duplicate_root or root_occurrences > 1
        if duplicate_root:
            raise RuntimeError("research factor graph has multiple scheduling paths")
        if root_count != len(self._factor_validation_roots):
            raise RuntimeError("research factor is missing from its owner graph")
        host_counts.clear()

        host_indicators = self._lineiterators[LineIterator.IndType]
        root_by_id = self._factor_validation_root_by_id
        expected_parents = self._factor_validation_expected_parents
        nested_ids = self._factor_validation_nested_ids
        for item in host_indicators:
            item_id = id(item)
            if item_id in nested_ids:
                raise RuntimeError("research factor graph changed during collection")
            if item_id in root_by_id:
                host_counts[item_id] = host_counts.get(item_id, 0) + 1
            elif item_id in expected_parents:
                raise RuntimeError("research factor graph changed during collection")
        for root in self._factor_validation_roots:
            if root._owner is not self or host_counts.get(id(root), 0) != 1:
                raise RuntimeError("research factor is missing from its owner graph")

        for parent, expected_children, expected_edge_count in self._factor_validation_parents:
            lineiterators = getattr(parent, "_lineiterators", {})
            child_counts.clear()
            edge_count = 0

            for type_key, children in lineiterators.items():
                for child in children:
                    child_id = id(child)
                    expected = expected_children.get(child_id)
                    if child._owner is not parent:
                        raise RuntimeError("research factor graph changed during collection")
                    if (
                        expected is None
                        or child._ltype != expected[0]
                        or type_key != expected[0]
                    ):
                        raise RuntimeError("research factor graph changed during collection")
                    expected_count = expected[1]
                    actual_count = child_counts.get(child_id, 0) + 1
                    if actual_count > expected_count:
                        raise RuntimeError("research factor graph changed during collection")
                    child_counts[child_id] = actual_count
                    edge_count += 1

            if edge_count != expected_edge_count:
                raise RuntimeError("research factor graph changed during collection")

        for node, was_factor in self._factor_validation_objects:
            if isinstance(node, FactorIndicator) is not was_factor:
                raise RuntimeError("research factor graph changed during collection")

        if self._factor_validation_duplicate_parent:
            raise RuntimeError("research factor graph has multiple scheduling paths")

        # Keep the full scheduler walk: another strategy can acquire a
        # protected node after initialization, and that must still fail.
        cerebro = getattr(self, "cerebro", None)
        strategies = tuple(getattr(cerebro, "runningstrats", ()))
        found_self = False
        for strategy in strategies:
            if strategy is self:
                found_self = True
            visited.clear()
            pending.clear()
            pending.append(strategy)
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
                            observed[child_id] = observed.get(child_id, 0) + 1
                        pending.append(child)
        if not found_self:
            visited.clear()
            pending.clear()
            pending.append(self)
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
                            observed[child_id] = observed.get(child_id, 0) + 1
                        pending.append(child)

        for child_id in expected_parents:
            if observed.get(child_id, 0) != 1:
                raise RuntimeError("research factor graph has multiple scheduling paths")

        return cerebro, strategies

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
