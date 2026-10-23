"""Native Backtrader strategy that collects a plain-frame research panel."""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, cast

from .. import Strategy
from ..utils import num2date
from ..errors import ResearchConfigError, DatasetError
from .factor_indicator import FactorIndicator
from .specs import (
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
        self._research = self.p.research
        if not isinstance(self._research, ResearchSpec):
            raise ResearchConfigError("FactorStrategy requires research=ResearchSpec(...)")
        if not self.datas:
            raise ResearchConfigError("FactorStrategy requires named target data feeds")
        if self._research.start > self._research.end:
            raise ResearchConfigError("research start must not follow end")
        self._sink = self.p.sink
        if self._sink is None:
            from .sink import MemorySink

            self._sink = MemorySink()
        else:
            from .sink import FactorSink

            if not isinstance(self._sink, FactorSink):
                raise ResearchConfigError("sink must be a FactorSink instance")
        self._panel: Any = None
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
                instance._bind_grid(self._calculation_times())
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
        self._field_counts = self._build_field_counts()

    def _calculation_times(self) -> Tuple[datetime, ...]:
        return tuple(value.to_pydatetime() for value in self._research.calculation_grid.index)

    def _validate_clocks(self) -> None:
        cerebro = getattr(self, "env", None)
        if bool(getattr(cerebro, "_doreplay", False)) or bool(getattr(cerebro, "_dolive", False)):
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
        if self._grid_cursor >= len(self._grid):
            current = num2date(float(self.datetime[0]), tz=timezone.utc, naive=False)
            if current > self._grid[-1]:
                return
            raise RuntimeError("FactorStrategy received more callbacks than the declared grid")
        current = num2date(float(self.datetime[0]), tz=timezone.utc, naive=False)
        if current != self._grid[self._grid_cursor]:
            raise RuntimeError("FactorStrategy callback time does not match the ResearchSpec grid")
        research = self._research
        in_research = research.start.to_pydatetime() <= current <= research.end.to_pydatetime()
        for asset, data in zip(research.targets, self._target_datas):
            present = self._feed_present(data, self._grid_cursor)
            current_bar = self._current_feed_time(data) == current and present
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
        for alias in _input_aliases(spec):
            counts = self._field_counts.get((id(data), alias))
            if counts is None:
                continue
            if int(counts[cursor + 1] - counts[start]) != expected:
                return False
        return True

    def _build_field_counts(self) -> Dict[Any, Any]:
        import numpy as np

        counts: Dict[Any, Any] = {}
        for data in self._target_datas:
            metadata = _alignment_metadata(data)
            if not isinstance(metadata, Mapping):
                continue
            fields = metadata.get("field_present") or {}
            for name, values in fields.items():
                counts[(id(data), str(name))] = _cumulative(values, np)
        return counts

    @staticmethod
    def _current_feed_time(data: Any) -> Optional[datetime]:
        try:
            return cast(datetime, num2date(float(data.datetime[0]), tz=timezone.utc, naive=False))
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
        from .sink import PanelContext

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
            closes[asset] = metadata["prices_close"]
        prices_open = pd.DataFrame(opens, index=grid.index) if complete else None
        prices_close = pd.DataFrame(closes, index=grid.index) if complete else None
        study_index = grid.index[(grid.index >= self._research.start) & (grid.index <= self._research.end)]
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
        if sys.exc_info()[0] is not None or any(
            bool(getattr(getattr(instance, "_factor_strict_context", None), "failed", False))
            for instances in self._factor_instances_by_name.values()
            for instance in instances
        ):
            return
        if self._grid_cursor != len(self._grid):
            raise RuntimeError("FactorStrategy did not sample every ResearchSpec grid point")
        for name, instances in self._factor_instances_by_name.items():
            for factor in instances:
                for nested in self._factor_tree(factor):
                    if not nested.lifecycle_diagnostics["grid_matches"]:
                        raise RuntimeError(
                            "factor %s did not run once per calculation-grid point" % name
                        )
        self._panel = self._sink.finalize(self._panel_context())
        self._sink.close()

    @staticmethod
    def _factor_tree(root: FactorIndicator) -> Tuple[FactorIndicator, ...]:
        result: List[FactorIndicator] = []
        seen = set()

        def visit(node: FactorIndicator) -> None:
            if id(node) in seen:
                return
            seen.add(id(node))
            result.append(node)
            for children in getattr(node, "_lineiterators", {}).values():
                for child in children:
                    if isinstance(child, FactorIndicator):
                        visit(child)

        visit(root)
        return tuple(result)

    def evaluate(self, spec: Any = None, **kwargs: Any) -> Any:
        """Evaluate the collected panel through the public research adapter."""
        from .fincore_adapter import evaluate_frames

        if spec is not None and kwargs:
            raise ResearchConfigError("pass either spec or evaluation keyword arguments, not both")
        if spec is None and kwargs:
            spec = kwargs
        return evaluate_frames(self.get_panel(), spec)


def _cumulative(values: Any, np: Any) -> Any:
    array = np.asarray(values, dtype=np.int64)
    return np.concatenate(([0], np.cumsum(array)))


def _input_aliases(spec: FactorSpec) -> Tuple[str, ...]:
    """Map declared formula fields to the feed columns whose values they read."""
    bindings = spec.field_bindings
    aliases: List[str] = []
    for alias in tuple(getattr(spec.indicator, "formula_fields", ())):
        binding = bindings.get(alias)
        resolved = _source_aliases(alias, binding, bindings)
        aliases.extend(resolved)
    return tuple(dict.fromkeys(aliases))


def _source_aliases(alias: str, binding: Any, bindings: Mapping) -> List[str]:
    if isinstance(binding, Mapping):
        derive = binding.get("derive")
        if derive == "adv":
            source = binding.get("source")
            return _source_aliases(source, bindings.get(source), bindings) if source else []
        if derive == "vwap_volume":
            output: List[str] = []
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
    return [parts[2]]


def _alignment_metadata(data: Any) -> Optional[Mapping]:
    metadata = getattr(data, _ALIGNMENT_V2, None)
    if isinstance(metadata, Mapping):
        return metadata
    metadata = getattr(data, _ALIGNMENT_V1, None)
    return metadata if isinstance(metadata, Mapping) else None


__all__ = ("FactorStrategy",)
