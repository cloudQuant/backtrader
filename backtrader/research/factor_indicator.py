"""Native Backtrader indicators with one real scalar output per target feed."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

from .. import Indicator
from ..indicators import SMA
from ..utils import date2num, num2date
from .errors import ConfigError, FactorComputationContext


class _OutputLines:
    """Attribute and item access to one target's real Backtrader output lines."""

    __slots__ = ("_lines",)

    def __init__(self, lines: Mapping[str, Any]) -> None:
        self._lines = dict(lines)

    def __getitem__(self, name: str) -> Any:
        return self._lines[name]

    def __getattr__(self, name: str) -> Any:
        try:
            return self._lines[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def keys(self) -> Tuple[str, ...]:
        return tuple(self._lines)


class _PITValueLine(Indicator):
    """Causal native line view over an already prealigned PIT input table.

    The line is indexed by the bound target feed's ordinary BT clock.  The
    table is frozen by the public alignment helper; user factor code sees only
    the current scalar line value and never receives the table or its arrays.
    """

    lines: Any = ("value",)
    params: Any = (("timestamps", ()), ("line_values", ()))

    def __init__(self) -> None:
        stamps = tuple(float(value) for value in self.p.timestamps)
        values = tuple(float(value) for value in self.p.line_values)
        if len(stamps) != len(values) or len(set(stamps)) != len(stamps):
            raise ValueError("prealigned PIT line must have unique timestamps and equal values")
        self._pit_values = dict(zip(stamps, values))

    def next(self) -> None:
        stamp = float(self.data.datetime[0])
        self.lines.value[0] = self._pit_values.get(stamp, float("nan"))


class _FeedInputLine(Indicator):
    """Native identity child that advances on a bound feed's own clock.

    A named feed can supply a formula field without becoming a parent factor
    clock or output target. Wrapping its source line as a child keeps that
    dependency scheduled in both runonce and runnext mode.
    """

    lines: Any = ("value",)

    def next(self) -> None:
        self.lines.value[0] = self.data[0]


class FactorIndicator(Indicator):
    """Base class for native, next-driven multi-target research factors.

    Concrete factors use the ordinary Indicator ``__init__``/``super()`` and
    ``next`` lifecycle.  ``bind`` builds a private native subclass with a real
    output line for each target and declared output template.  Research code
    should normally let :class:`FactorStrategy` construct the bound instance.
    """

    lines: Any = ()
    params: Any = ()
    aliased = True
    panel_mode = "next"
    formula_fields: Tuple[str, ...] = ()
    classification_fields: Tuple[str, ...] = ()

    def __init__(self) -> None:
        if not getattr(self.__class__, "_factor_bound", False):
            raise TypeError("FactorIndicator instances must be created through bind()")

        raw_output_datas = getattr(self.__class__, "_factor_output_datas", self.datas)
        output_datas = tuple(cast(Sequence[Any], raw_output_datas))
        output_names = getattr(self.__class__, "_factor_output_names", ())
        if len(output_datas) != len(output_names):
            raise RuntimeError("bound factor outputs do not match their line layout")

        self._factor_target_datas = output_datas
        self.outputs: Dict[Any, _OutputLines] = {}
        for data, names in zip(output_datas, output_names):
            feed_lines: Dict[str, Any] = {}
            for template, alias in names:
                line = getattr(self.lines, alias)
                if not hasattr(line, "array") or not hasattr(line, "advance"):
                    raise RuntimeError("factor output is not a Backtrader line")
                feed_lines[template] = line
            self.outputs[data] = _OutputLines(feed_lines)

        runtime = getattr(self.__class__, "_factor_runtime", None)
        self._factor_runtime: Mapping[str, Any] = runtime or {}
        asset_names = tuple(self._factor_runtime.get("asset_names", ()))
        if asset_names and len(asset_names) != len(output_datas):
            raise RuntimeError("factor asset names do not match its output lines")
        self._factor_asset_names = asset_names
        self._factor_call_times: List[datetime] = []
        self._factor_grid: Optional[Tuple[datetime, ...]] = None
        self._factor_value_states: Dict[Tuple[datetime, int, str], Dict[str, Any]] = {}
        self._field_line_cache: Dict[str, Tuple[Any, ...]] = {}
        self._class_line_cache: Dict[str, Tuple[Any, ...]] = {}
        self._factor_input_metadata: Dict[
            Tuple[int, str, bool], Dict[datetime, Dict[str, Any]]
        ] = {}
        self._formula_member_lines: Optional[Tuple[Any, ...]] = None

        factor_name = self._factor_runtime.get("factor_name")
        context = self._factor_runtime.get("strict_context")
        if factor_name and context is not None:
            object.__setattr__(self, "_factor_strict_context", context)
            object.__setattr__(self.lines, "_factor_strict_context", context)
            for data, outputs in self.outputs.items():
                asset = self._factor_runtime["asset_by_data_id"][id(data)]
                for line in outputs._lines.values():
                    context.bind_object(line, asset)
                    line._factor_strict_context = context

        # Register every declared input before the engine starts scheduling
        # siblings. This also captures source-side availability metadata for
        # fields that a formula only reads through a native child operator.
        for alias in tuple(getattr(self.__class__, "formula_fields", ())):
            self.field_lines(alias)
        for alias in tuple(getattr(self.__class__, "classification_fields", ())):
            self.classification_lines(alias)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        is_bound = bool(cls.__dict__.get("_factor_bound", False))
        if not is_bound:
            raw_lines = cls.__dict__.get("lines")
            if not isinstance(raw_lines, (tuple, list)) or not raw_lines:
                raise TypeError("each concrete factor class must declare line templates")
            if "next" not in cls.__dict__ and not any(
                "next" in base.__dict__ and base is not FactorIndicator for base in cls.__mro__[1:]
            ):
                raise TypeError("each concrete factor class must implement next()")
            if getattr(cls, "panel_mode", None) != "next":
                raise TypeError("FactorIndicator requires explicit panel_mode='next'")
            if any(name in cls.__dict__ for name in ("build", "expression")):
                raise TypeError("build/expression factor declarations are not implemented")

        super().__init_subclass__(**kwargs)
        if is_bound:
            return

        next_impl = cls.__dict__.get("next")
        if next_impl is not None and not getattr(next_impl, "_factor_counted", False):

            @wraps(next_impl)
            def counted_next(self: "FactorIndicator", *args: Any, **next_kwargs: Any) -> Any:
                self._record_factor_call()
                return next_impl(self, *args, **next_kwargs)

            setattr(counted_next, "_factor_counted", True)
            setattr(cls, "next", counted_next)

    def prenext(self) -> None:
        """Run user formulas while dependencies warm up, preserving real NaNs."""
        self.next()

    def nextstart(self) -> None:
        """Use the same formula on the first bar meeting the native minperiod."""
        self.next()

    def next(self) -> None:
        raise NotImplementedError("concrete factor classes must implement next()")

    @classmethod
    def bind(cls, *datas: Any, **params: Any) -> "FactorIndicator":
        """Build a native feed-local factor whose outputs match its inputs.

        The operator-compatible binding API treats each declared formula field
        as the same-named native feed line. ResearchStrategy uses the narrower
        ``_bind_for_research`` path, where every source is supplied explicitly
        through its immutable FactorSpec.
        """
        native_field_bindings = {
            alias: "feed:target:%s" % alias for alias in tuple(getattr(cls, "formula_fields", ()))
        }
        return cls._bind_for_research(
            *datas,
            output_datas=datas,
            asset_names=tuple(getattr(data, "_name", "") for data in datas),
            factor_name=None,
            field_bindings=native_field_bindings,
            classification_bindings={},
            research=None,
            **params,
        )

    @classmethod
    def _bind_for_research(
        cls,
        *datas: Any,
        output_datas: Sequence[Any],
        asset_names: Sequence[str],
        factor_name: Optional[str],
        field_bindings: Mapping[str, Any],
        classification_bindings: Mapping[str, str],
        research: Any,
        available_datas: Optional[Sequence[Any]] = None,
        strict: bool = True,
        **params: Any,
    ) -> "FactorIndicator":
        """Construct one native factor with explicit target/input separation."""
        cls._validate_bind_request(datas)
        targets = tuple(output_datas)
        names = tuple(asset_names)
        if not targets or len(targets) != len(names) or len(set(names)) != len(names):
            raise ConfigError("factor output targets and unique asset names are required")
        if any(data not in datas for data in targets):
            raise ConfigError("factor output targets must be native indicator inputs")
        if not isinstance(field_bindings, Mapping) or not isinstance(
            classification_bindings, Mapping
        ):
            raise ConfigError("factor input bindings must be mappings")

        templates = cls._factor_template_names()
        output_names = tuple(
            tuple((template, "target_%d__%s" % (index, template)) for template in templates)
            for index in range(len(targets))
        )
        concrete_lines = tuple(alias for item in output_names for _, alias in item)
        asset_by_data_id = {id(data): name for data, name in zip(targets, names)}
        input_datas = tuple(available_datas) if available_datas is not None else tuple(datas)
        runtime = {
            "asset_names": names,
            "asset_by_data_id": asset_by_data_id,
            "factor_name": factor_name if strict else None,
            "field_bindings": dict(field_bindings),
            "classification_bindings": dict(classification_bindings),
            "research": research,
            "output_data_ids": tuple(id(data) for data in targets),
            "available_datas": input_datas,
        }
        context = None
        if strict and factor_name:
            context = FactorComputationContext(str(factor_name), phase="construct")
            for data in input_datas:
                asset = asset_by_data_id.get(id(data)) or getattr(data, "_name", None)
                if isinstance(asset, str) and asset:
                    context.bind_object(data, asset)
            runtime["strict_context"] = context
        bound_class = type(
            "_Bound_%s" % cls.__name__,
            (cls,),
            {
                "__module__": cls.__module__,
                "_factor_bound": True,
                "_mindatas": len(datas),
                "_factor_output_datas": targets,
                "_factor_output_names": output_names,
                "_factor_runtime": runtime,
                "lines": concrete_lines,
            },
        )
        if context is not None:
            cls._validate_bound_sources(context, input_datas, targets, field_bindings)
            context.phase = "init"
        try:
            instance = bound_class(*datas, **params)
        except Exception as exc:
            if context is None:
                raise
            wrapped = context.wrap(
                exc,
                phase="init",
                asset=names[0] if len(names) == 1 else None,
            )
            context.failed = True
            setattr(context, "error", wrapped)
            if wrapped is exc:
                raise
            raise wrapped from exc
        finally:
            if context is not None:
                context.phase = "construct"
        if not hasattr(instance, "outputs"):
            raise RuntimeError(
                "factor __init__ must call super().__init__() before creating child indicators"
            )
        if len(instance.datas) != len(datas) or any(
            actual is not expected for actual, expected in zip(instance.datas, datas)
        ):
            raise RuntimeError("Backtrader did not bind the requested factor feeds")
        if set(instance.outputs) != set(targets):
            raise RuntimeError("factor output-line binding is incomplete")
        return cast("FactorIndicator", instance)

    @staticmethod
    def _validate_bound_sources(
        context: FactorComputationContext,
        datas: Sequence[Any],
        output_datas: Sequence[Any],
        field_bindings: Mapping[str, Any],
    ) -> None:
        """Reject infinities in explicitly bound feed fields before preload.

        Backtrader preserves its historical infinity-to-zero conversion for
        ordinary feeds. After feed preload, research factors inspect the still
        retained PandasData input only for formula fields they explicitly bind,
        before constructing the factor tree.
        """
        from .strict import validate_bound_feed_source

        by_name = {getattr(data, "_name", ""): data for data in datas}
        visiting = set()

        def validate_binding(binding: Any) -> None:
            if isinstance(binding, Mapping):
                derive = binding.get("derive")
                if derive == "adv":
                    source_alias = binding.get("source")
                    if isinstance(source_alias, str) and source_alias not in visiting:
                        visiting.add(source_alias)
                        validate_binding(field_bindings.get(source_alias))
                        visiting.remove(source_alias)
                    return
                if derive == "vwap_volume":
                    for source_alias in (binding.get("vwap"), binding.get("volume")):
                        if isinstance(source_alias, str) and source_alias not in visiting:
                            visiting.add(source_alias)
                            validate_binding(field_bindings.get(source_alias))
                            visiting.remove(source_alias)
                    return
                binding = binding.get("source")
            if not isinstance(binding, str) or not binding.startswith("feed:"):
                return
            parts = binding.split(":")
            if len(parts) != 3:
                return
            feed_name, field_name = parts[1], parts[2]
            if feed_name == "target":
                source_feeds = output_datas
            else:
                source = by_name.get(feed_name)
                source_feeds = (source,) if source is not None else ()
            for source_feed in source_feeds:
                validate_bound_feed_source(context, source_feed, field_name, "construct")

        for alias, binding in field_bindings.items():
            if alias in visiting:
                continue
            validate_binding(binding)

    @classmethod
    def _validate_bind_request(cls, datas: Sequence[Any]) -> None:
        if cls is FactorIndicator or not issubclass(cls, FactorIndicator):
            raise TypeError("bind() must be called on a concrete FactorIndicator subclass")
        if getattr(cls, "panel_mode", None) != "next":
            raise TypeError("only native panel_mode='next' factors are supported")
        if any(name in base.__dict__ for base in cls.__mro__ for name in ("build", "expression")):
            raise TypeError("expression/build factor declarations are not implemented")
        if cls.next is FactorIndicator.next:
            raise TypeError("factor class has no concrete next() implementation")
        if not datas:
            raise ValueError("a factor requires at least one data feed")
        if any(data is None or not hasattr(data, "lines") for data in datas):
            raise TypeError("all factor inputs must be Backtrader line-series objects")
        if len({id(data) for data in datas}) != len(datas):
            raise ValueError("factor inputs must not contain the same feed twice")
        if not cls._factor_template_names():
            raise TypeError("factor class has no output-line templates")

    @classmethod
    def _factor_template_names(cls) -> Tuple[str, ...]:
        declared = getattr(cls, "lines", ())
        if hasattr(declared, "getlinealiases"):
            aliases = tuple(declared.getlinealiases())
        elif isinstance(declared, (tuple, list)):
            aliases = tuple(declared)
        else:
            aliases = ()
        return tuple(name for name in aliases if isinstance(name, str) and name)

    def _bind_grid(self, grid: Tuple[datetime, ...]) -> None:
        """Attach the caller's UTC grid to this factor and native descendants."""
        self._bind_grid_tree(tuple(grid), set())

    def _bind_grid_tree(self, grid: Tuple[datetime, ...], seen: set) -> None:
        if id(self) in seen:
            return
        seen.add(id(self))
        if self._factor_grid is not None and self._factor_grid != grid:
            raise RuntimeError("factor grid is already bound to a different sequence")
        self._factor_grid = tuple(grid)
        for children in getattr(self, "_lineiterators", {}).values():
            for child in children:
                if isinstance(child, FactorIndicator):
                    child._bind_grid_tree(grid, seen)

    def _record_factor_call(self) -> None:
        data = self._factor_target_datas[0] if self._factor_target_datas else self.datas[0]
        current = num2date(float(data.datetime[0]), tz=timezone.utc, naive=False)
        index = len(self._factor_call_times)
        if self._factor_grid is not None:
            if index >= len(self._factor_grid):
                raise RuntimeError("factor next() ran more than once for the requested grid")
            if current != self._factor_grid[index]:
                raise RuntimeError("factor next() time does not match its next UTC grid point")
        self._factor_call_times.append(current)

    @property
    def lifecycle_diagnostics(self) -> Dict[str, Any]:
        """Read-only count and UTC-grid observations for lifecycle acceptance."""
        calls = tuple(self._factor_call_times)
        grid = self._factor_grid
        return {
            "call_count": len(calls),
            "call_times": calls,
            "grid_count": len(grid or ()),
            "grid_matches": bool(grid is not None and calls == grid),
        }

    def output_for(self, data: Any, line: str = "factor") -> Any:
        """Return the real Backtrader output line for one target/template."""
        try:
            return self.outputs[data][line]
        except KeyError as exc:
            raise KeyError("unknown factor target or output template") from exc

    @property
    def target_datas(self) -> Tuple[Any, ...]:
        """The feeds whose assets receive one real output-line set each."""
        return tuple(self._factor_target_datas)

    @property
    def available_datas(self) -> Tuple[Any, ...]:
        """All named feeds available to explicit input bindings.

        ``datas`` remains the native calculation-clock dependencies. A named
        benchmark can be resolved as an input without making it an output
        target or an additional FactorIndicator clock.
        """
        return tuple(self._factor_runtime.get("available_datas", self.datas))

    def field_lines(self, alias: str) -> Tuple[Any, ...]:
        """Resolve a declared raw/derived formula field to target-ordered lines.

        Default target fields are lines with the same name as *alias*. Explicit
        field bindings may name another feed, a prealigned table, or one exact
        ``derive_adv`` rolling-mean recipe.
        """
        if alias in self._field_line_cache:
            return self._field_line_cache[alias]
        declared = tuple(getattr(self.__class__, "formula_fields", ()))
        if alias not in declared:
            raise ConfigError("factor did not declare formula field %s" % alias)
        binding = self._factor_runtime.get("field_bindings", {}).get(alias)
        if binding is None:
            raise ConfigError("factor field %s has no explicit binding" % alias)
        lines = self._resolve_bound_lines(alias, binding, classification=False, stack=())
        self._bind_input_metadata_alias(alias, binding, classification=False)
        self._field_line_cache[alias] = lines
        return lines

    def field(self, alias: str, data: Any) -> Any:
        """Resolve one target's formula input line by its actual feed object."""
        lines = self.field_lines(alias)
        try:
            index = self._factor_target_datas.index(data)
        except ValueError as exc:
            raise ConfigError("field access requires a factor target feed") from exc
        return lines[index]

    def classification_lines(self, alias: str) -> Tuple[Any, ...]:
        """Resolve one explicitly declared PIT classification binding per target."""
        if alias in self._class_line_cache:
            return self._class_line_cache[alias]
        declared = tuple(getattr(self.__class__, "classification_fields", ()))
        levels = tuple(getattr(self.__class__, "classification_levels", ()))
        if alias not in declared and alias not in levels:
            raise ConfigError("factor did not declare classification field %s" % alias)
        binding = self._factor_runtime.get("classification_bindings", {}).get(alias)
        if binding is None:
            raise ConfigError("classification %s has no explicit binding" % alias)
        if ":" not in binding:
            research = self._factor_runtime.get("research")
            if research is None or binding not in research.classifications:
                raise ConfigError("classification binding is not a named ResearchSpec table")
            binding = "table:" + binding
        lines = self._resolve_bound_lines(alias, binding, classification=True, stack=())
        self._bind_input_metadata_alias(alias, binding, classification=True)
        self._class_line_cache[alias] = lines
        return lines

    def _bind_input_metadata_alias(self, alias: str, binding: Any, *, classification: bool) -> None:
        """Associate source PIT metadata with the factor's declared alias."""
        if isinstance(binding, Mapping):
            derive = binding.get("derive")
            if derive == "adv":
                source = binding.get("source")
                if isinstance(source, str) and source in self._factor_runtime.get(
                    "field_bindings", {}
                ):
                    self.field_lines(source)
                return
            if derive == "vwap_volume":
                for source in (binding.get("vwap"), binding.get("volume")):
                    if isinstance(source, str) and source in self._factor_runtime.get(
                        "field_bindings", {}
                    ):
                        self.field_lines(source)
                return
            binding = binding.get("source")
        if not isinstance(binding, str):
            return
        if binding.startswith("table:"):
            table_name = binding.split(":", 1)[1]
            for data in self._factor_target_datas:
                table_state = self._factor_input_metadata.get(
                    (id(data), table_name, classification)
                )
                if table_state is not None:
                    self._factor_input_metadata[(id(data), alias, classification)] = table_state
            return
        if binding.startswith("feed:"):
            if classification:
                raise ConfigError(
                    "classification bindings require a named PIT table with taxonomy metadata"
                )
            pieces = binding.split(":")
            if len(pieces) == 3 and pieces[1] and pieces[2]:
                self._record_feed_input_metadata(
                    alias, pieces[1], pieces[2], classification=classification
                )

    def _record_feed_input_metadata(
        self, alias: str, feed_name: str, line_name: str, *, classification: bool
    ) -> None:
        """Record aligned feed availability and original source timestamps."""
        available_datas = tuple(self._factor_runtime.get("available_datas", self.datas))
        by_name = {getattr(data, "_name", ""): data for data in available_datas}
        if feed_name == "target":
            sources = self._factor_target_datas
        else:
            source = by_name.get(feed_name)
            sources = (source,) * len(self._factor_target_datas) if source is not None else ()
        if len(sources) != len(self._factor_target_datas):
            return
        research = self._factor_runtime.get("research")
        if research is None:
            return
        grid = tuple(value.to_pydatetime() for value in research.calculation_grid.index)
        for target, source in zip(self._factor_target_datas, sources):
            metadata = getattr(source, "_factor_research_alignment_v1", None)
            present_values = (
                tuple(metadata.get("present", ())) if isinstance(metadata, Mapping) else ()
            )
            available_values = (
                tuple(metadata.get("available_at", ())) if isinstance(metadata, Mapping) else ()
            )
            frame = getattr(getattr(source, "p", None), "dataname", None)
            frame_data = cast(Any, frame)
            column: Optional[Tuple[Any, ...]] = None
            if hasattr(frame_data, "columns") and line_name in frame_data.columns:
                try:
                    column = tuple(frame_data[line_name].to_numpy())
                except (AttributeError, TypeError, ValueError):
                    column = None
            states: Dict[datetime, Dict[str, Any]] = {}
            for index, point in enumerate(grid):
                is_present = bool(present_values[index]) if index < len(present_values) else True
                source_available = (
                    available_values[index] if index < len(available_values) else point
                )
                if source_available is not None and hasattr(source_available, "to_pydatetime"):
                    source_available = source_available.to_pydatetime()
                if not is_present:
                    reason = "NO_CURRENT_BAR"
                elif source_available is not None and source_available > point:
                    reason = "NOT_YET_AVAILABLE"
                elif column is not None and index < len(column) and _is_nan(column[index]):
                    reason = "NONFINITE_INPUT"
                else:
                    reason = "READY"
                states[point] = {
                    "present": is_present,
                    "available_at": source_available,
                    "reason": reason,
                }
            self._factor_input_metadata[(id(target), alias, classification)] = states

    @property
    def formula_members(self) -> Tuple[Any, ...]:
        """Native current-grid formula-universe membership lines by target."""
        if self._formula_member_lines is not None:
            return self._formula_member_lines
        research = self._factor_runtime.get("research")
        if research is None:
            self._formula_member_lines = (None,) * len(self._factor_target_datas)
            return self._formula_member_lines
        membership = research.formula_universe
        grid = research.calculation_grid
        stamps = tuple(float(date2num(value.to_pydatetime())) for value in grid.index)
        members = []
        for data in self._factor_target_datas:
            asset = self._factor_runtime["asset_by_data_id"][id(data)]
            alignment = getattr(data, "_factor_research_alignment_v1", None)
            present = tuple(alignment.get("present", ())) if isinstance(alignment, Mapping) else ()
            values = tuple(
                float(bool(membership.loc[(time, asset)]) and (not present or bool(present[index])))
                for index, time in enumerate(grid.index)
            )
            line = cast(Any, _PITValueLine)(data, timestamps=stamps, line_values=values)
            members.append(line.lines.value)
        self._formula_member_lines = tuple(members)
        return self._formula_member_lines

    @property
    def research_groups(self) -> Tuple[str, ...]:
        """Static group keys ordered exactly like the target output lines."""
        research = self._factor_runtime.get("research")
        if research is None:
            return tuple("default" for _ in self._factor_target_datas)
        groups = research.groups
        return tuple(
            groups[self._factor_runtime["asset_by_data_id"][id(data)]]
            for data in self._factor_target_datas
        )

    def input_availability(
        self,
        data: Any,
        point: datetime,
        *,
        start_index: int,
        end_index: int,
    ) -> Dict[str, Any]:
        """Return source timestamps and a conservative PIT status by alias."""
        result: Dict[str, Any] = {}
        aliases = tuple(getattr(self.__class__, "formula_fields", ())) + tuple(
            getattr(self.__class__, "classification_fields", ())
        )
        for alias in aliases:
            classification = alias in tuple(getattr(self.__class__, "classification_fields", ()))
            states = self._factor_input_metadata.get((id(data), alias, classification))
            if not states:
                # A normal target-feed line is released at its aligned close.
                grid = self._factor_grid or ()
                result[alias] = {
                    "available_at": tuple(
                        grid[index]
                        for index in range(max(0, start_index), min(end_index + 1, len(grid)))
                    ),
                    "reason": None,
                }
                continue
            stamps: List[Optional[datetime]] = []
            reason: Optional[str] = None
            grid = self._factor_grid or ()
            for index in range(max(0, start_index), min(end_index + 1, len(grid))):
                input_point = grid[index]
                state = states.get(input_point)
                if state is None:
                    stamps.append(None)
                    reason = "MISSING_FIELD"
                    continue
                source_available = state.get("available_at")
                stamps.append(source_available)
                input_reason = state.get("reason")
                if input_reason not in (None, "READY"):
                    # Keep the first concrete failure in chronological order;
                    # its timestamp remains in the parallel input_times row.
                    if reason is None:
                        reason = input_reason
            result[alias] = {"available_at": tuple(stamps), "reason": reason}
        return result

    @staticmethod
    def _mark_target_local_line(line: Any, target: Any, sources: Sequence[Any]) -> Any:
        """Retain a target only when every derivation source proves that target."""
        if not sources:
            return line
        target_lines = getattr(getattr(target, "lines", None), "lines", ())
        for source in sources:
            marker = getattr(source, "_factor_research_target", None)
            if marker is not None:
                if marker is not target:
                    return line
                continue
            if source is target or any(source is target_line for target_line in target_lines):
                continue
            # Unknown and named-feed sources keep their existing clock behavior.
            return line
        line._factor_research_target = target
        return line

    def _resolve_bound_lines(
        self,
        alias: str,
        binding: Any,
        *,
        classification: bool,
        stack: Tuple[str, ...],
    ) -> Tuple[Any, ...]:
        if alias in stack:
            raise ConfigError("cyclic factor field binding: %s" % alias)
        if isinstance(binding, Mapping):
            kind = binding.get("derive")
            if kind == "adv":
                source = binding.get("source")
                window = binding.get("window")
                if (
                    not isinstance(alias, str)
                    or not alias.startswith("adv")
                    or not alias[3:].isdigit()
                    or type(window) is not int
                    or window < 1
                    or int(alias[3:]) != window
                    or not isinstance(source, str)
                    or not source
                ):
                    raise ConfigError("derived ADV binding must match alias advN and window N")
                source_lines = self._resolve_bound_lines(
                    source,
                    self._factor_runtime.get("field_bindings", {}).get(source),
                    classification=False,
                    stack=stack + (alias,),
                )
                sma_type = cast(Any, SMA)
                result = tuple(
                    self._mark_target_local_line(
                        sma_type(line, period=window).lines.sma, target, (line,)
                    )
                    for target, line in zip(self._factor_target_datas, source_lines)
                )
                return result
            if kind == "vwap_volume":
                if alias != "dollar_volume":
                    raise ConfigError("vwap_volume derivation only defines dollar_volume")
                vwap_alias = binding.get("vwap")
                volume_alias = binding.get("volume")
                if not isinstance(vwap_alias, str) or not isinstance(volume_alias, str):
                    raise ConfigError("vwap_volume source aliases must be strings")
                vwap_lines = self._resolve_bound_lines(
                    vwap_alias,
                    self._factor_runtime.get("field_bindings", {}).get(vwap_alias),
                    classification=False,
                    stack=stack + (alias,),
                )
                volume_lines = self._resolve_bound_lines(
                    volume_alias,
                    self._factor_runtime.get("field_bindings", {}).get(volume_alias),
                    classification=False,
                    stack=stack + (alias,),
                )
                if len(vwap_lines) != len(volume_lines):
                    raise ConfigError("vwap and volume sources must align per target")
                return tuple(
                    self._mark_target_local_line(vwap * volume, target, (vwap, volume))
                    for target, vwap, volume in zip(
                        self._factor_target_datas, vwap_lines, volume_lines
                    )
                )
            if binding.get("kind") == "direct":
                binding = binding.get("source")
            else:
                raise ConfigError("unknown field binding descriptor")
        if not isinstance(binding, str):
            raise ConfigError("field %s has no explicit binding" % alias)
        if binding.startswith("table:"):
            return self._table_lines(
                binding.split(":", 1)[1],
                classification=classification,
                expected_level=alias if classification else None,
            )
        if binding.startswith("feed:"):
            pieces = binding.split(":")
            if len(pieces) != 3 or not pieces[1] or not pieces[2]:
                raise ConfigError("feed bindings must use feed:<name>:<line>")
            feed_name, line_name = pieces[1], pieces[2]
            if feed_name == "target":
                try:
                    return tuple(getattr(data, line_name) for data in self._factor_target_datas)
                except AttributeError as exc:
                    raise ConfigError("target feed is missing a required formula line") from exc
            if feed_name == "target":
                try:
                    return tuple(getattr(data, line_name) for data in self._factor_target_datas)
                except AttributeError as exc:
                    raise ConfigError("target feed is missing a required formula line") from exc
            named = {
                getattr(data, "_name", ""): data
                for data in self._factor_runtime.get("available_datas", self.datas)
                if getattr(data, "_name", "") == feed_name
            }
            if feed_name not in named:
                raise ConfigError("factor binding references an unknown named feed")
            try:
                line = getattr(named[feed_name], line_name)
            except AttributeError as exc:
                raise ConfigError("named feed is missing a bound line") from exc
            bound_line = cast(Any, _FeedInputLine)(line).lines.value
            return (bound_line,) * len(self._factor_target_datas)
        raise ConfigError("field %s requires an explicit feed: or table: binding" % alias)

    def _table_lines(
        self, name: str, *, classification: bool, expected_level: Optional[str] = None
    ) -> Tuple[Any, ...]:
        research = self._factor_runtime.get("research")
        if research is None:
            raise ConfigError("table bindings require a ResearchSpec")
        tables = research.classifications if classification else research.formula_fields
        if name not in tables:
            raise ConfigError("ResearchSpec has no bound input table %s" % name)
        if classification:
            table = tables[name]
            declared_levels = tuple(getattr(self.__class__, "classification_levels", ()))
            if expected_level is None or expected_level not in declared_levels:
                raise ConfigError("classification table requires an explicit declared level")
            table_levels = set(table["level"].dropna().tolist())
            if table_levels != {expected_level}:
                raise ConfigError("classification table level does not match the factor binding")
        from .inputs import prealign_pit_table

        aligned = prealign_pit_table(tables[name], research, name, classification=classification)
        values_frame = aligned.values
        value_column = "category" if classification else "value"
        table_values = values_frame[value_column]
        present = aligned.present
        available_at = aligned.available_at
        reasons = aligned.reason
        if classification:
            known = set()
            for value in table_values:
                if value is None or _is_nan(value):
                    continue
                if isinstance(value, str) and not value.strip():
                    raise ConfigError("classification categories must be non-empty strings")
                try:
                    known.add((type(value), value))
                except TypeError as exc:
                    raise ConfigError("classification categories must be hashable scalars") from exc
            ordered = sorted(
                known,
                key=lambda item: (
                    getattr(item[0], "__module__", ""),
                    getattr(item[0], "__qualname__", item[0].__name__),
                    repr(item[1]),
                ),
            )
            codebook = {value: float(index + 1) for index, value in enumerate(ordered)}
            values_by_key = {
                (time, asset): codebook.get((type(value), value), float("nan"))
                for (time, asset), value in table_values.items()
            }
        else:
            try:
                values_by_key = {
                    (time, asset): float(value) if not _is_nan(value) else float("nan")
                    for (time, asset), value in table_values.items()
                }
            except (TypeError, ValueError, OverflowError) as exc:
                raise ConfigError("formula input tables must expose numeric values") from exc

        grid = research.calculation_grid
        stamps = tuple(float(date2num(value.to_pydatetime())) for value in grid.index)
        output = []
        for data in self._factor_target_datas:
            asset = self._factor_runtime["asset_by_data_id"][id(data)]
            series = tuple(values_by_key.get((time, asset), float("nan")) for time in grid.index)
            line = cast(Any, _PITValueLine)(data, timestamps=stamps, line_values=series)
            line.lines.value._factor_research_target = data
            output.append(line.lines.value)
            states: Dict[datetime, Dict[str, Any]] = {}
            for time in grid.index:
                key = (time, asset)
                source_time = available_at.loc[key]
                states[time.to_pydatetime()] = {
                    "present": bool(present.loc[key]),
                    "available_at": (
                        source_time.to_pydatetime()
                        if source_time is not None and not _is_nan(source_time)
                        else None
                    ),
                    "reason": str(reasons.loc[key]),
                }
            self._factor_input_metadata[(id(data), name, classification)] = states
            if classification:
                setattr(line, "_factor_classification_codebook", dict(codebook))
        return tuple(output)

    def record_availability(
        self,
        data: Any,
        *,
        ready: bool,
        valid: bool,
        reason: str,
        available_at: Optional[datetime] = None,
        input_times: Any = None,
        line: str = "factor",
    ) -> None:
        """Record current-grid eligibility facts for the collector.

        Formula implementations with richer reason lines should call this
        alongside writing their scalar output.  The collector supplies a
        conservative reason when an implementation does not.
        """
        if data not in self.outputs or line not in self.outputs[data].keys():
            raise ConfigError("availability must refer to an actual factor output")
        if type(ready) is not bool or type(valid) is not bool or not isinstance(reason, str):
            raise ConfigError("availability requires bool readiness and a reason string")
        if valid and not ready:
            raise ConfigError("a valid output must also be ready")
        point = num2date(float(data.datetime[0]), tz=timezone.utc, naive=False)
        self._factor_value_states[(point, id(data), line)] = {
            "time": point,
            "ready": ready,
            "valid": valid,
            "reason": reason,
            "available_at": available_at or point,
            "input_times": input_times,
        }

    def availability_for(self, data: Any, line: str, point: datetime) -> Optional[Dict[str, Any]]:
        """Return a copy of formula-authored availability for this grid point."""
        state = self._factor_value_states.get((point, id(data), line))
        if state is None:
            return None
        return dict(state)


def _is_nan(value: Any) -> bool:
    if value is None or type(value).__name__ in ("NAType", "NaTType"):
        return True
    if isinstance(value, str):
        return False
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError, OverflowError):
        # String categories are valid PIT classifications; only explicit
        # missing sentinels are absent here.
        return False


__all__ = ("FactorIndicator",)
