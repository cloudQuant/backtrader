"""Native Backtrader indicators with one real scalar output per target feed."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

from .. import Indicator
from ..indicators import SMA
from ..utils import date2num, num2date
from ..errors import ResearchConfigError, FactorComputationContext


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


class _PresenceLine(Indicator):
    """One boolean real-bar flag per bar, advancing on the target feed clock.

    Cross-sectional operators read it to exclude an asset whose source feed has
    no bar on the current grid point.  It carries no point-in-time table, source
    timestamp or availability reason.
    """

    lines: Any = ("value",)
    params: Any = (("present", ()),)

    def __init__(self) -> None:
        self._present = tuple(bool(value) for value in self.p.present)
        self._cursor = 0

    def next(self) -> None:
        index = self._cursor
        self._cursor += 1
        if index >= len(self._present):
            self.lines.value[0] = 1.0
        else:
            self.lines.value[0] = 1.0 if self._present[index] else 0.0


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

    def __init__(self) -> None:
        if not getattr(self.__class__, "_factor_bound", False):
            raise TypeError("FactorIndicator instances must be created through bind()")

        raw_output_datas = getattr(self.__class__, "_factor_output_datas", self.datas)
        output_datas = tuple(cast(Sequence[Any], raw_output_datas))
        output_names = getattr(self.__class__, "_factor_output_names", ())
        if len(output_datas) != len(output_names):
            raise RuntimeError("bound factor outputs do not match their line layout")

        self._factor_target_datas = output_datas
        self._factor_target_index_by_id: Dict[int, int] = {}
        for index, data in enumerate(output_datas):
            self._factor_target_index_by_id.setdefault(id(data), index)
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
        self._factor_call_times: List[datetime] = []
        self._factor_grid: Optional[Tuple[datetime, ...]] = None
        self._field_line_cache: Dict[str, Tuple[Any, ...]] = {}
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
        # siblings.
        for alias in tuple(getattr(self.__class__, "formula_fields", ())):
            self.field_lines(alias)

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
            raise ResearchConfigError("factor output targets and unique asset names are required")
        input_data_ids = {id(data) for data in datas}
        if any(id(data) not in input_data_ids for data in targets):
            raise ResearchConfigError("factor output targets must be native indicator inputs")
        if not isinstance(field_bindings, Mapping):
            raise ResearchConfigError("factor input bindings must be a mapping")

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
            "research": research,
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
        field bindings may name another feed's ordinary line or one exact
        ``derive_adv`` rolling-mean recipe.
        """
        if alias in self._field_line_cache:
            return self._field_line_cache[alias]
        declared = tuple(getattr(self.__class__, "formula_fields", ()))
        if alias not in declared:
            raise ResearchConfigError("factor did not declare formula field %s" % alias)
        binding = self._factor_runtime.get("field_bindings", {}).get(alias)
        if binding is None:
            raise ResearchConfigError("factor field %s has no explicit binding" % alias)
        lines = self._resolve_bound_lines(alias, binding, stack=())
        self._field_line_cache[alias] = lines
        return lines

    def field(self, alias: str, data: Any) -> Any:
        """Resolve one target's formula input line by its actual feed object."""
        lines = self.field_lines(alias)
        index = self._factor_target_index_by_id.get(id(data))
        if index is None:
            raise ResearchConfigError("field access requires a factor target feed")
        return lines[index]

    @property
    def formula_members(self) -> Tuple[Any, ...]:
        """One static real-bar membership line per target.

        A grid point where the source feed has no bar excludes that asset from
        cross-sectional operators.  This replaces the deleted dynamic
        ``formula_universe`` table; NaN/finite input handling stays with the
        operators' own reason lines.
        """
        if self._formula_member_lines is not None:
            return self._formula_member_lines
        members = []
        for data in self._factor_target_datas:
            alignment = getattr(data, "_factor_research_alignment_v2", None)
            if not isinstance(alignment, Mapping):
                alignment = getattr(data, "_factor_research_alignment_v1", None)
            present = tuple(alignment.get("present", ())) if isinstance(alignment, Mapping) else ()
            members.append(cast(Any, _PresenceLine)(data, present=present).lines.value)
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
        stack: Tuple[str, ...],
    ) -> Tuple[Any, ...]:
        if alias in stack:
            raise ResearchConfigError("cyclic factor field binding: %s" % alias)
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
                    raise ResearchConfigError(
                        "derived ADV binding must match alias advN and window N"
                    )
                source_lines = self._resolve_bound_lines(
                    source,
                    self._factor_runtime.get("field_bindings", {}).get(source),
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
                    raise ResearchConfigError("vwap_volume derivation only defines dollar_volume")
                vwap_alias = binding.get("vwap")
                volume_alias = binding.get("volume")
                if not isinstance(vwap_alias, str) or not isinstance(volume_alias, str):
                    raise ResearchConfigError("vwap_volume source aliases must be strings")
                vwap_lines = self._resolve_bound_lines(
                    vwap_alias,
                    self._factor_runtime.get("field_bindings", {}).get(vwap_alias),
                    stack=stack + (alias,),
                )
                volume_lines = self._resolve_bound_lines(
                    volume_alias,
                    self._factor_runtime.get("field_bindings", {}).get(volume_alias),
                    stack=stack + (alias,),
                )
                if len(vwap_lines) != len(volume_lines):
                    raise ResearchConfigError("vwap and volume sources must align per target")
                return tuple(
                    self._mark_target_local_line(vwap * volume, target, (vwap, volume))
                    for target, vwap, volume in zip(
                        self._factor_target_datas, vwap_lines, volume_lines
                    )
                )
            if binding.get("kind") == "direct":
                binding = binding.get("source")
            else:
                raise ResearchConfigError("unknown field binding descriptor")
        if not isinstance(binding, str):
            raise ResearchConfigError("field %s has no explicit binding" % alias)
        if binding.startswith("feed:"):
            pieces = binding.split(":")
            if len(pieces) != 3 or not pieces[1] or not pieces[2]:
                raise ResearchConfigError("feed bindings must use feed:<name>:<line>")
            feed_name, line_name = pieces[1], pieces[2]
            if feed_name == "target":
                try:
                    return tuple(getattr(data, line_name) for data in self._factor_target_datas)
                except AttributeError as exc:
                    raise ResearchConfigError(
                        "target feed is missing a required formula line"
                    ) from exc
            named = {
                getattr(data, "_name", ""): data
                for data in self._factor_runtime.get("available_datas", self.datas)
                if getattr(data, "_name", "") == feed_name
            }
            if feed_name not in named:
                raise ResearchConfigError("factor binding references an unknown named feed")
            try:
                line = getattr(named[feed_name], line_name)
            except AttributeError as exc:
                raise ResearchConfigError("named feed is missing a bound line") from exc
            bound_line = cast(Any, _FeedInputLine)(line).lines.value
            return (bound_line,) * len(self._factor_target_datas)
        raise ResearchConfigError("field %s requires an explicit feed:<name>:<line> binding" % alias)

__all__ = ("FactorIndicator",)
