"""Native Backtrader strategy that collects a validated research dataset."""

from __future__ import annotations

import math
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

from .. import Strategy
from ..utils import num2date
from .errors import ConfigError, DatasetError
from .factor_indicator import FactorIndicator
from .specs import FactorSpec, ResearchSpec, normalize_factor_specs, thaw


_FEED_ALIGNMENT = "_factor_research_alignment_v1"


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
        self._nodes = self._merge_nodes()

    def _merge_nodes(self) -> Dict[str, Any]:
        """Present group-local formula traces in original target order."""
        per_asset: Dict[str, Any] = {}
        shared: Dict[str, Dict[Any, Any]] = {}
        for instance in self.group_instances.values():
            for name, node in getattr(instance, "_nodes", {}).items():
                match = re.match(r"^(.*)_([0-9]+)$", name)
                node_outputs = getattr(node, "outputs", None)
                if match and isinstance(node_outputs, Mapping) and len(node_outputs) == 1:
                    local_index = int(match.group(2))
                    if local_index < len(instance.datas):
                        data = instance.datas[local_index]
                        global_index = self.datas.index(data)
                        per_asset["%s_%d" % (match.group(1), global_index)] = node
                        continue
                if isinstance(node_outputs, Mapping):
                    shared.setdefault(name, {}).update(node_outputs)
                else:
                    per_asset[name] = node

        merged = dict(per_asset)
        for name, node_outputs in shared.items():
            merged[name] = _MergedFactorNode(self.datas, node_outputs)
        return merged

    def field_lines(self, alias: str) -> Tuple[Any, ...]:
        by_data: Dict[int, Any] = {}
        for instance in self.group_instances.values():
            for data, line in zip(instance.target_datas, instance.field_lines(alias)):
                by_data[id(data)] = line
        return tuple(by_data[id(data)] for data in self.datas)

    def classification_lines(self, alias: str) -> Tuple[Any, ...]:
        by_data: Dict[int, Any] = {}
        for instance in self.group_instances.values():
            for data, line in zip(instance.target_datas, instance.classification_lines(alias)):
                by_data[id(data)] = line
        return tuple(by_data[id(data)] for data in self.datas)

    @property
    def formula_members(self) -> Tuple[Any, ...]:
        by_data: Dict[int, Any] = {}
        for instance in self.group_instances.values():
            for data, line in zip(instance.target_datas, instance.formula_members):
                by_data[id(data)] = line
        return tuple(by_data[id(data)] for data in self.datas)

    @property
    def research_groups(self) -> Tuple[str, ...]:
        by_data: Dict[int, str] = {}
        for instance in self.group_instances.values():
            by_data.update(
                (id(data), group)
                for data, group in zip(instance.target_datas, instance.research_groups)
            )
        return tuple(by_data[id(data)] for data in self.datas)

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


class _MergedFactorNode:
    """Small output-only view over same-named group-local native nodes."""

    def __init__(self, datas: Sequence[Any], outputs: Mapping[Any, Any]) -> None:
        self.datas = tuple(data for data in datas if data in outputs)
        self.outputs = {data: outputs[data] for data in self.datas}


class FactorStrategy(Strategy):
    """Construct native factor indicators and sample their output lines.

    Cerebro owns all indicator and feed clocks. The strategy only samples each
    callback and seals the result as a :class:`ResearchDataset` after the run.
    """

    params = (("research", None), ("factors", None))

    def __init__(self) -> None:
        self._research = self.p.research
        if not isinstance(self._research, ResearchSpec):
            raise ConfigError("FactorStrategy requires research=ResearchSpec(...)")
        if not self.datas:
            raise ConfigError("FactorStrategy requires named target data feeds")

        self._data_names = tuple(getattr(data, "_name", "") for data in self.datas)
        if any(not isinstance(name, str) or not name for name in self._data_names):
            raise ConfigError("every FactorStrategy feed needs a non-empty Cerebro name")
        if len(set(self._data_names)) != len(self._data_names):
            raise ConfigError("FactorStrategy feed names must be unique")
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

        self._factor_specs = normalize_factor_specs(self.p.factors)
        self.factor_instances: Dict[str, Any] = {}
        self._factor_specs_by_name: Dict[str, FactorSpec] = dict(self._factor_specs)
        self._factor_instances_by_name: Dict[str, Tuple[FactorIndicator, ...]] = {}
        self._factor_instance_by_data: Dict[str, Dict[int, FactorIndicator]] = {}
        for name, spec in self._factor_specs_by_name.items():
            if spec.panel_line not in spec.indicator._factor_template_names():
                raise ConfigError("factor %s selects an unknown panel_line" % name)
            declared_fields = tuple(getattr(spec.indicator, "formula_fields", ()))
            declared_classes = tuple(getattr(spec.indicator, "classification_fields", ()))
            missing_fields = set(declared_fields) - set(spec.field_bindings)
            missing_classes = set(declared_classes) - set(spec.classification_bindings)
            if missing_fields:
                raise DatasetError(
                    "factor %s is missing explicit field bindings: %s"
                    % (name, sorted(missing_fields)),
                    code="MISSING_INPUT",
                    report={"factor": name, "missing_fields": tuple(sorted(missing_fields))},
                )
            if missing_classes:
                raise DatasetError(
                    "factor %s is missing explicit classification bindings: %s"
                    % (name, sorted(missing_classes)),
                    code="MISSING_INPUT",
                    report={
                        "factor": name,
                        "missing_classifications": tuple(sorted(missing_classes)),
                    },
                )
            self._validate_bindings(spec)
            from .field_validation import validate_factor_field_metadata

            validate_factor_field_metadata(spec, self._research, self.datas, self._target_datas)

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
                    classification_bindings=spec.classification_bindings,
                    research=self._research,
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
        self._raw_rows: List[Dict[str, Any]] = []
        self._availability_rows: List[Dict[str, Any]] = []
        self._price_rows: List[Dict[str, Any]] = []
        self._dataset: Any = None

    def _calculation_times(self) -> Tuple[datetime, ...]:
        return tuple(value.to_pydatetime() for value in self._research.calculation_grid.index)

    def _validate_clocks(self) -> None:
        cerebro = getattr(self, "env", None)
        if bool(getattr(cerebro, "_doreplay", False)) or bool(getattr(cerebro, "_dolive", False)):
            raise ConfigError(
                "FactorStrategy does not support live or replay Cerebro clocks",
                code="UNSUPPORTED_CLOCK",
            )
        clocks = []
        for data in self.datas:
            live = getattr(data, "islive", None)
            if callable(live) and live():
                raise ConfigError(
                    "FactorStrategy does not support live feed clocks",
                    code="UNSUPPORTED_CLOCK",
                )
            if bool(getattr(data, "replaying", False)) or bool(getattr(data, "resampling", False)):
                raise ConfigError(
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
            raise ConfigError(
                "FactorStrategy requires one synchronized feed timeframe",
                code="UNSUPPORTED_CLOCK",
            )

    def _validate_bindings(self, spec: FactorSpec) -> None:
        for alias, binding in spec.field_bindings.items():
            if isinstance(binding, str):
                source = binding
            elif isinstance(binding, Mapping):
                if binding.get("derive") in ("adv", "vwap_volume"):
                    if binding.get("derive") == "adv":
                        source_alias = binding.get("source")
                        if not isinstance(source_alias, str):
                            raise ConfigError("derived ADV source alias must be a string")
                        source_value: Any = spec.field_bindings.get(source_alias, "")
                        if isinstance(source_value, Mapping):
                            if source_value.get("derive") not in ("vwap_volume", None):
                                raise ConfigError("derived ADV source is not dollar_volume")
                        elif not str(source_value).endswith(":dollar_volume"):
                            raise ConfigError("derived ADV source must bind dollar_volume")
                    continue
                source = binding.get("source", "")
            else:
                raise ConfigError("factor field bindings must be qualified")
            if isinstance(source, str) and source.startswith("table:"):
                table = source.split(":", 1)[1]
                if table not in self._research.formula_fields:
                    raise DatasetError(
                        "factor field binding references an unknown formula table",
                        code="MISSING_INPUT",
                        report={"factor": spec.name, "field": alias, "table": table},
                    )
            elif isinstance(source, str) and source.startswith("feed:"):
                parts = source.split(":")
                if len(parts) != 3 or (parts[1] != "target" and parts[1] not in self._data_names):
                    raise DatasetError(
                        "factor field binding references an unknown feed",
                        code="MISSING_INPUT",
                        report={"factor": spec.name, "field": alias, "feed": parts[1]},
                    )
            else:
                raise ConfigError("factor field binding must use a qualified feed or table")
        for alias, binding in spec.classification_bindings.items():
            if binding.startswith("table:"):
                table = binding.split(":", 1)[1]
                if table not in self._research.classifications:
                    raise DatasetError(
                        "classification binding references an unknown table",
                        code="MISSING_INPUT",
                        report={"factor": spec.name, "classification": alias, "table": table},
                    )
                self._validate_classification_level(spec, alias, table)
            elif binding.startswith("feed:"):
                raise ConfigError(
                    "classification bindings require a named PIT table with taxonomy metadata"
                )
            elif binding in self._research.classifications:
                # A bare, exact key is still an explicit ResearchSpec table
                # binding; it is never interpreted as a same-named feed line.
                self._validate_classification_level(spec, alias, binding)
            else:
                raise ConfigError("classification bindings require an explicit named PIT table")

    def _validate_classification_level(self, spec: FactorSpec, alias: str, table_name: str) -> None:
        """Reject taxonomy-level mismatches before constructing an algorithm."""
        indicator = spec.indicator
        fields = tuple(getattr(indicator, "classification_fields", ()))
        levels = tuple(getattr(indicator, "classification_levels", ()))
        expected: Optional[str] = None
        if alias in fields and len(fields) == len(levels):
            expected = cast(str, levels[fields.index(alias)])
        elif levels and len(set(levels)) == 1:
            expected = cast(str, levels[0])
        elif alias in levels:
            expected = alias
        if expected is None:
            raise ConfigError(
                "factor %s has no unambiguous declared classification level for %s"
                % (spec.name, alias)
            )

        table = self._research.classifications[table_name]
        actual_levels = set(table["level"].dropna().tolist())
        if actual_levels != {expected}:
            raise ConfigError(
                "classification table level does not match the factor binding",
                report={
                    "factor": spec.name,
                    "classification": alias,
                    "table": table_name,
                    "expected_level": expected,
                    "actual_levels": tuple(sorted(str(value) for value in actual_levels)),
                },
            )

    def prenext(self) -> None:
        self._collect_current_grid_point()

    def nextstart(self) -> None:
        self._collect_current_grid_point()

    def next(self) -> None:
        self._collect_current_grid_point()

    def _collect_current_grid_point(self) -> None:
        if self._grid_cursor == len(self._grid):
            current = num2date(float(self.datetime[0]), tz=timezone.utc, naive=False)
            if current > self._grid[-1]:
                return
        if self._grid_cursor >= len(self._grid):
            raise RuntimeError("FactorStrategy received more callbacks than the declared grid")
        current = num2date(float(self.datetime[0]), tz=timezone.utc, naive=False)
        expected = self._grid[self._grid_cursor]
        if current != expected:
            raise RuntimeError("FactorStrategy callback time does not match the ResearchSpec grid")

        research = self._research
        in_research = research.start.to_pydatetime() <= current <= research.end.to_pydatetime()
        for index, (asset, data) in enumerate(zip(research.targets, self._target_datas)):
            feed_time = self._current_feed_time(data)
            present = self._feed_present(data, self._grid_cursor)
            current_bar = feed_time == current and present
            row = {"time": current, "asset": asset}
            availability_at_point: List[Dict[str, Any]] = []
            for name, indicator in self.factor_instances.items():
                spec = self._factor_specs_by_name[name]
                indicator = self._factor_instance_by_data[name][id(data)]
                raw_value = (
                    float(indicator.outputs[data][spec.panel_line][0])
                    if current_bar
                    else float("nan")
                )
                state = indicator.availability_for(data, spec.panel_line, current)
                reason, ready, valid = self._classify_output(
                    indicator,
                    spec,
                    data,
                    current,
                    raw_value,
                    current_bar,
                    state,
                    self._grid_cursor,
                )
                if not valid:
                    raw_value = float("nan")
                row[name] = raw_value
                if in_research:
                    input_times = self._input_times(indicator, spec, data, current, state)
                    availability_at_point.append(
                        {
                            "time": current,
                            "asset": asset,
                            "factor": name,
                            "ready": ready,
                            "valid": valid,
                            "reason": reason,
                            "available_at": current if ready else None,
                            "input_times": input_times,
                        }
                    )
            self._raw_rows.append(row)
            if in_research:
                self._availability_rows.extend(availability_at_point)
            self._price_rows.append(
                {
                    "time": current,
                    "asset": asset,
                    "open": self._line_value(data, "open") if current_bar else float("nan"),
                    "close": self._line_value(data, "close") if current_bar else float("nan"),
                }
            )
        self._grid_cursor += 1

    def _classify_output(
        self,
        indicator: FactorIndicator,
        spec: FactorSpec,
        data: Any,
        point: datetime,
        value: float,
        current_bar: bool,
        state: Optional[Mapping[str, Any]],
        grid_index: int,
    ) -> Tuple[str, bool, bool]:
        if not current_bar:
            return "NO_CURRENT_BAR", False, False
        for alias in tuple(getattr(spec.indicator, "formula_fields", ())) + tuple(
            getattr(spec.indicator, "classification_fields", ())
        ):
            input_start = max(0, grid_index - spec.lookback_h)
            details = indicator.input_availability(
                data, point, start_index=input_start, end_index=grid_index
            ).get(alias, {})
            reason = details.get("reason")
            if reason in (
                "MISSING_FIELD",
                "NOT_YET_AVAILABLE",
                "UNKNOWN_CLASSIFICATION",
                "NO_CURRENT_BAR",
                "FORMULA_INELIGIBLE",
            ):
                return str(reason), False, False
            if reason == "NONFINITE_INPUT":
                return "NONFINITE_INPUT", True, False
        if state is not None:
            reason = str(state["reason"])
            return reason, bool(state["ready"]), bool(state["valid"] and math.isfinite(value))
        if grid_index < spec.lookback_h:
            return "INCOMPLETE_WINDOW", False, False
        if math.isfinite(value):
            return "READY", True, True
        return "DOMAIN_ERROR", True, False

    def _input_times(
        self,
        indicator: FactorIndicator,
        spec: FactorSpec,
        data: Any,
        point: datetime,
        state: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        names = tuple(getattr(spec.indicator, "formula_fields", ())) + tuple(
            getattr(spec.indicator, "classification_fields", ())
        )
        output: Dict[str, Any] = {"target_close": point}
        start_index = max(0, self._grid_cursor - spec.lookback_h)
        details = indicator.input_availability(
            data, point, start_index=start_index, end_index=max(0, self._grid_cursor)
        )
        for alias in names:
            values = details.get(alias, {}).get("available_at", ())
            if not values:
                output[alias] = None
            elif spec.lookback_h:
                output[alias] = tuple(values)
            else:
                output[alias] = values[-1]
        if isinstance(state, Mapping) and isinstance(state.get("input_times"), Mapping):
            output.update(state["input_times"])
        return output

    @staticmethod
    def _current_feed_time(data: Any) -> Optional[datetime]:
        try:
            return cast(datetime, num2date(float(data.datetime[0]), tz=timezone.utc, naive=False))
        except (IndexError, TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _feed_present(data: Any, index: int) -> bool:
        metadata = getattr(data, _FEED_ALIGNMENT, None)
        if not isinstance(metadata, Mapping):
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

    def get_dataset(
        self,
        *,
        prices: Optional[Mapping[str, Any]] = None,
        provenance: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        """Seal and return a defensive ResearchDataset after Cerebro finishes."""
        if self._grid_cursor != len(self._grid):
            raise RuntimeError("dataset is unavailable before the full grid has run")
        if self._dataset is not None and prices is None and provenance is None:
            return self._dataset
        pd = self._pandas()
        factor_names = tuple(self.factor_instances)
        panel = pd.DataFrame(self._raw_rows, columns=("time", "asset") + factor_names)
        panel = panel.set_index(["time", "asset"])
        availability = pd.DataFrame(self._availability_rows)
        if len(availability):
            availability = availability.set_index(["time", "asset", "factor"])
        else:
            availability = pd.DataFrame(
                columns=("ready", "valid", "reason", "available_at", "input_times"),
                index=pd.MultiIndex.from_tuples((), names=("time", "asset", "factor")),
            )
        if prices is None:
            full_grid = self._research.grid.index
            open_values: Dict[str, Sequence[float]] = {}
            close_values: Dict[str, Sequence[float]] = {}
            complete_full_prices = True
            for asset, data in zip(self._research.targets, self._target_datas):
                metadata = getattr(data, _FEED_ALIGNMENT, None)
                source_prices = (
                    metadata.get("full_prices") if isinstance(metadata, Mapping) else None
                )
                if not isinstance(source_prices, Mapping):
                    complete_full_prices = False
                    break
                opens = source_prices.get("open")
                closes = source_prices.get("close")
                if (
                    opens is None
                    or closes is None
                    or len(opens) != len(full_grid)
                    or len(closes) != len(full_grid)
                ):
                    complete_full_prices = False
                    break
                open_values[asset] = tuple(opens)
                close_values[asset] = tuple(closes)
            if complete_full_prices:
                price_tables: Mapping[str, Any] = {
                    "open": pd.DataFrame(open_values, index=full_grid),
                    "close": pd.DataFrame(close_values, index=full_grid),
                }
            else:
                # Custom feeds may not come from prealign_bars. Preserve only
                # prices actually observed by this native calculation clock.
                observed = pd.DataFrame(self._price_rows)
                price_tables = {
                    "open": observed.pivot(index="time", columns="asset", values="open"),
                    "close": observed.pivot(index="time", columns="asset", values="close"),
                }
        else:
            price_tables = prices
        metadata = {
            "factor_specs": {
                name: spec.to_metadata() for name, spec in self._factor_specs_by_name.items()
            },
            "factor_directions": {
                name: spec.direction for name, spec in self._factor_specs_by_name.items()
            },
            "research_grid_sha256": self._research.grid_sha256,
        }
        if provenance:
            metadata.update(dict(provenance))
        from .field_validation import collect_bound_feed_tables

        formula_inputs = dict(self._research.formula_fields)
        bound_feed_tables = collect_bound_feed_tables(
            self._factor_specs_by_name,
            self._research,
            self.datas,
            self._target_datas,
        )
        collisions = set(formula_inputs).intersection(bound_feed_tables)
        if collisions:
            raise ConfigError(
                "formula table names conflict with collected feed bindings",
                report={"tables": tuple(sorted(collisions))},
            )
        formula_inputs.update(bound_feed_tables)
        from .dataset import ResearchDataset

        self._dataset = ResearchDataset.from_collection(
            research=self._research,
            raw_factors=panel,
            availability=availability,
            prices=price_tables,
            formula_inputs=formula_inputs,
            classifications=self._research.classifications,
            provenance=metadata,
        )
        return self._dataset

    def evaluate(self, spec: Any = None, **kwargs: Any) -> Any:
        """Evaluate the sealed dataset through the public research adapter."""
        from .fincore_adapter import evaluate_dataset

        return evaluate_dataset(self.get_dataset(), spec=spec, **kwargs)

    @staticmethod
    def _pandas() -> Any:
        from .specs import require_research_runtime

        return require_research_runtime()


__all__ = ("FactorStrategy",)
