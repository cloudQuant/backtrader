"""Backtrader research factors with one real scalar output per target feed."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from functools import wraps
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

from ..feed import AbstractDataBase
from ..feeds.pandafeed import PandasData
from ..indicator import Indicator
from ..indicators import SMA
from ..linebuffer import LineBuffer
from ..lineiterator import LineIterator
from ..lineseries import Lines
from ..utils import num2date
from ..errors import ResearchConfigError, FactorComputationContext


_FACTOR_ONCE_FEED_ADVANCE = AbstractDataBase.advance
_FACTOR_ONCE_FEED_TICK_NULLIFY = AbstractDataBase._tick_nullify
_FACTOR_ONCE_FEED_TICK_FILL = AbstractDataBase._tick_fill
_FACTOR_ONCE_ITERATOR_ADVANCE = LineIterator.advance
_FACTOR_ONCE_INDICATOR_ADVANCE = Indicator.advance
_FACTOR_ONCE_LINES_ADVANCE = Lines.advance
_FACTOR_ONCE_LINE_ADVANCE = LineBuffer.advance
_LIVE_FACTOR_DIAGNOSTIC_SAMPLE_LIMIT = 64


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


def _factor_once_method_owner(instance: Any, name: str) -> Optional[type]:
    """Return the class that supplies one callback on *instance*."""
    for candidate in type(instance).__mro__:
        if name in candidate.__dict__:
            return candidate
    return None


def _factor_once_method_is(instance: Any, name: str, expected: Any) -> bool:
    """Check an overridable instance hook against its imported implementation."""
    try:
        method = object.__getattribute__(instance, name)
    except (AttributeError, TypeError):
        return False
    return getattr(method, "__self__", None) is instance and getattr(
        method, "__func__", None
    ) is expected


def _factor_once_lines_ready(instance: Any, end: int, seen: set) -> bool:
    """Check that a full-array node can be read at absolute once indexes."""
    if id(instance) in seen:
        return True
    seen.add(id(instance))

    if isinstance(instance, Indicator):
        if not _factor_once_method_is(
            instance, "advance", _FACTOR_ONCE_INDICATOR_ADVANCE
        ):
            return False
    elif isinstance(instance, LineIterator) and not _factor_once_method_is(
        instance, "advance", _FACTOR_ONCE_ITERATOR_ADVANCE
    ):
        return False

    lines = getattr(instance, "lines", None)
    if lines is not None:
        if not _factor_once_method_is(lines, "advance", _FACTOR_ONCE_LINES_ADVANCE):
            return False
        for line in lines:
            # The kernel sets these cursors directly to avoid one advance per
            # feed/child/bar. Keep this limited to the exact standard buffer.
            if type(line) is not LineBuffer or not _factor_once_method_is(
                line, "advance", _FACTOR_ONCE_LINE_ADVANCE
            ):
                return False
            if getattr(line, "mode", None) != getattr(line, "UnBounded", 0):
                return False
            if len(line.array) < end:
                return False

    children = getattr(instance, "_lineiterators", {})
    for child in children.get(LineIterator.IndType, ()):
        if not _factor_once_lines_ready(child, end, seen):
            return False
    return True


def _factor_once_supported(
    instance: Any, optimized_class: type, start: int, end: int
) -> bool:
    """Limit array indexing to the synchronized, full-array research path.

    Exact PandasData instances are the feeds produced by ``align_to_grid``.
    Subclasses and other feeds retain their ordinary Cerebro callbacks, as do
    custom callback overrides, qbuffers and indicators pinned to a distinct
    secondary-feed clock.
    """
    if start < 0 or end < start:
        return False
    if getattr(instance, "factor_mode", "native") != "native":
        return False
    instance_type = type(instance)
    if isinstance(instance, FactorIndicator):
        if (
            instance_type.__bases__ != (optimized_class,)
            or instance_type.__dict__.get("_factor_bound") is not True
        ):
            return False
    elif instance_type is not optimized_class:
        return False
    if _factor_once_method_owner(instance, "next") is not optimized_class:
        return False
    if _factor_once_method_owner(instance, "once") is not optimized_class:
        return False
    expected_callbacks = optimized_class.__dict__.get("_factor_once_expected_callbacks")
    if not isinstance(expected_callbacks, tuple) or any(
        not _factor_once_method_is(instance, name, method)
        for name, method in expected_callbacks
    ):
        return False

    # Preserve user-defined warmup callbacks. FactorIndicator supplies the
    # ordinary next-delegating defaults; a standard Indicator uses LineIterator.
    allowed_prenext = (optimized_class, FactorIndicator, LineIterator)
    allowed_nextstart = (optimized_class, FactorIndicator, LineIterator)
    if _factor_once_method_owner(instance, "prenext") not in allowed_prenext:
        return False
    if _factor_once_method_owner(instance, "nextstart") not in allowed_nextstart:
        return False

    try:
        datas = tuple(instance.datas)
        clock = object.__getattribute__(instance, "_clock")
    except (AttributeError, TypeError):
        return False
    if not datas or clock is not datas[0]:
        return False
    resolved_clock = getattr(instance, "_resolved_secondary_clock", None)
    if resolved_clock is not None and resolved_clock is not datas[0]:
        return False

    for data in datas:
        if (
            type(data) is not PandasData
            or end > data.buflen()
            or not _factor_once_method_is(data, "advance", _FACTOR_ONCE_FEED_ADVANCE)
            or not _factor_once_method_is(
                data, "_tick_nullify", _FACTOR_ONCE_FEED_TICK_NULLIFY
            )
            or not _factor_once_method_is(data, "_tick_fill", _FACTOR_ONCE_FEED_TICK_FILL)
            or not _factor_once_lines_ready(data, end, set())
        ):
            return False
    return _factor_once_lines_ready(instance, end, set())


def _factor_once_execute(
    instance: Any,
    optimized_class: type,
    callback: Any,
    start: int,
    end: int,
    *,
    phase: str = "once_via_next",
) -> bool:
    """Execute one supported array range under the ordinary strict phase."""
    if not _factor_once_supported(instance, optimized_class, start, end):
        return False
    instance._factor_run_callback(callback, phase, start, end)
    if isinstance(instance, FactorIndicator):
        instance._record_factor_once(start, end)
    return True


def _factor_once_read(line: Any, index: int, ago: int = 0) -> Any:
    """Read one preloaded line value through its ordinary strict line API."""
    line._idx = index
    line.lencount = index + 1
    return line[ago]


def _factor_once_write(line: Any, index: int, value: Any) -> None:
    """Store one result through the ordinary strict and bound line API."""
    line._idx = index
    line.lencount = index + 1
    line[0] = value


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
    """Base class for native and expression-driven multi-target research factors.

    Native factors use the ordinary Indicator ``__init__``/``super()`` and
    ``next`` lifecycle. Expression factors provide a classmethod ``build`` that
    returns one expression over the declared target fields. ``bind`` builds a
    private native subclass with a real output line for each target and
    declared output template. Research code should normally let
    :class:`FactorStrategy` construct the bound instance.
    """

    lines: Any = ()
    params: Any = ()
    aliased = True
    panel_mode = "next"
    formula_fields: Tuple[str, ...] = ()
    _factor_declared_params: Mapping[str, Any] = MappingProxyType({})

    def __init__(self) -> None:
        if not getattr(self.__class__, "_factor_bound", False):
            raise TypeError("FactorIndicator instances must be created through bind()")
        selected_mode = getattr(self.__class__, "_factor_runtime", {}).get("mode")
        if selected_mode == "build" and getattr(self, "_expression_initialization_started", False):
            raise RuntimeError("expression factors may only be initialized once")

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
        self._factor_live_bounded_diagnostics = bool(
            runtime.get("live_source_binding", False)
        )
        self._factor_call_count = 0
        self._factor_once_range_count = 0
        self._factor_once_covered_count = 0
        if self._factor_live_bounded_diagnostics:
            self._factor_call_times = deque(maxlen=_LIVE_FACTOR_DIAGNOSTIC_SAMPLE_LIMIT)
            self._factor_once_ranges = deque(maxlen=_LIVE_FACTOR_DIAGNOSTIC_SAMPLE_LIMIT)
        else:
            self._factor_call_times: List[datetime] = []
            self._factor_once_ranges: List[Tuple[int, int]] = []
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

        if selected_mode == "build":
            self._initialize_expression()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        is_bound = bool(cls.__dict__.get("_factor_bound", False))
        if not is_bound:
            cls._validate_factor_declaration(check_raw_lines=True)
            declared_params: Dict[str, Any] = {}
            for base in reversed(cls.__mro__[1:]):
                if (
                    isinstance(base, type)
                    and base is not FactorIndicator
                    and issubclass(base, FactorIndicator)
                ):
                    declared_params.update(base.__dict__.get("_factor_declared_params", {}))
            declared_params.update(cls._read_declared_params(cls.__dict__.get("params", ())))
            if "mode" in declared_params:
                raise TypeError("factor parameter 'mode' is reserved for FactorSpec/bind mode")
            cls._factor_declared_params = MappingProxyType(declared_params)

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

    @staticmethod
    def _read_declared_params(params: Any) -> Dict[str, Any]:
        """Read the author's original parameters before ParamsMixin merges them."""
        if params is None:
            return {}
        if isinstance(params, Mapping):
            return dict(params.items())
        if isinstance(params, (tuple, list)):
            declared: Dict[str, Any] = {}
            for item in params:
                if isinstance(item, (tuple, list)) and len(item) >= 2:
                    declared[item[0]] = item[1]
                elif isinstance(item, str):
                    declared[item] = None
                elif hasattr(item, "__iter__"):
                    pair = list(item)
                    if len(pair) >= 2:
                        declared[pair[0]] = pair[1]
            return declared
        if hasattr(params, "items"):
            return dict(params.items())
        if hasattr(params, "_getpairs"):
            return dict(params._getpairs())
        if hasattr(params, "_gettuple"):
            return dict(params._gettuple())
        if hasattr(params, "__dict__"):
            return {
                name: value
                for name, value in params.__dict__.items()
                if not name.startswith("_") and not callable(value)
            }
        return {}

    @classmethod
    def _resolve_factor_params(cls, params: Mapping[str, Any]) -> Dict[str, Any]:
        """Validate overrides and return this factor's resolved parameters."""
        if not isinstance(params, Mapping):
            raise ResearchConfigError("factor params must be a mapping")
        if any(not isinstance(name, str) for name in params):
            raise ResearchConfigError("factor parameter names must be strings")
        defaults = dict(getattr(cls, "_factor_declared_params", {}))
        unknown = set(params) - set(defaults)
        if unknown:
            raise ResearchConfigError("unsupported factor params: %s" % sorted(unknown))
        defaults.update(params)
        return defaults

    def prenext(self) -> None:
        """Run user formulas while dependencies warm up, preserving real NaNs."""
        self.next()

    def nextstart(self) -> None:
        """Use the same formula on the first bar meeting the native minperiod."""
        self.next()

    def next(self) -> None:
        if self._factor_runtime.get("mode") != "build":
            raise NotImplementedError("concrete factor classes must implement next()")
        self._record_factor_call()
        template = self._factor_template_names()[0]
        for data, result in zip(self._factor_target_datas, self._result_lines):
            self.outputs[data][template][0] = result[0]

    def _initialize_expression(self) -> None:
        """Build one native operator graph and retain its target result lines."""
        from ._expression import _ExpressionContext
        from .specs import _lookback

        if getattr(self, "_expression_initialization_started", False):
            raise RuntimeError("expression factors may only be initialized once")
        # Keep the guard set even if build() fails. A subclass that catches an
        # initialization error and retries super().__init__ must not build a
        # second graph on the same bound instance.
        object.__setattr__(self, "_expression_initialization_started", True)
        context = _ExpressionContext(self)
        resolved_params = dict(self._factor_runtime.get("factor_params", {}))
        try:
            result = self.__class__.build(context, **resolved_params)
            result_lines = context.result_lines(result)
        finally:
            context._close()
        self._expression_context = context
        self._nodes = context.nodes
        self._result_lines = result_lines
        lookback_h = _lookback(self.__class__, resolved_params)
        # The declaration is authoritative even when the graph's child
        # minperiods would otherwise make the parent ready earlier.
        self.addminperiod(lookback_h + 1)

    @classmethod
    def _validate_factor_declaration(cls, *, check_raw_lines: bool = False) -> str:
        """Validate one concrete factor and return its implicit selection mode."""
        if check_raw_lines:
            raw_lines = cls.__dict__.get("lines")
            if raw_lines is None:
                if not cls._factor_template_names():
                    raise TypeError(
                        "each concrete factor class must declare or inherit line templates"
                    )
            elif not isinstance(raw_lines, (tuple, list)) or not raw_lines:
                raise TypeError("each concrete factor class must declare line templates")

        next_impl = cls._factor_method("next")
        if next_impl is not None and not callable(next_impl):
            raise TypeError("factor next() must be callable")
        native_available = callable(next_impl) and next_impl is not FactorIndicator.next
        build_impl = cls._factor_method("build")
        build_available = build_impl is not None
        if build_available and not isinstance(build_impl, classmethod):
            raise TypeError("factor build() must be defined as a classmethod")
        if not native_available and not build_available:
            raise TypeError(
                "each concrete factor class must implement next() or classmethod build()"
            )

        if build_available:
            if len(cls._factor_template_names()) != 1:
                raise TypeError("build factors must declare exactly one output line")
            if any("expression" in base.__dict__ for base in cls.__mro__):
                raise TypeError("factor classes cannot declare expression()")
            formula_fields = getattr(cls, "formula_fields", ())
            if isinstance(formula_fields, str) or not isinstance(formula_fields, (tuple, list)):
                raise TypeError("build formula_fields must be a tuple or list of field names")
            fields = tuple(formula_fields)
            if any(not isinstance(field, str) or not field for field in fields):
                raise TypeError("build formula_fields must contain non-empty field names")
            if len(set(fields)) != len(fields):
                raise TypeError("build formula_fields must not contain duplicates")

        return "native" if native_available else "build"

    @classmethod
    def _factor_method(cls, name: str) -> Any:
        """Return the nearest author-declared method, excluding this base class."""
        for base in cls.__mro__:
            if base is FactorIndicator:
                break
            if name in base.__dict__:
                return base.__dict__[name]
        return None

    @classmethod
    def _resolve_factor_mode(cls, mode: Optional[str] = None) -> str:
        """Resolve a requested mode against methods available on this class."""
        if mode not in (None, "native", "build"):
            raise ValueError("factor mode must be None, 'native', or 'build'")
        next_impl = cls._factor_method("next")
        native_available = callable(next_impl) and next_impl is not FactorIndicator.next
        build_impl = cls._factor_method("build")
        build_available = isinstance(build_impl, classmethod)
        selected = mode
        if selected is None:
            selected = "native" if native_available else "build"
        if selected == "native" and not native_available:
            raise NotImplementedError(
                "factor class %s has no native next() implementation" % cls.__name__
            )
        if selected == "build" and not build_available:
            raise NotImplementedError("factor class %s has no classmethod build()" % cls.__name__)
        return selected

    @classmethod
    def bind(cls, *datas: Any, mode: Optional[str] = None, **params: Any) -> "FactorIndicator":
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
            mode=mode,
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
        mode: Optional[str] = None,
        available_datas: Optional[Sequence[Any]] = None,
        strict: bool = True,
        **params: Any,
    ) -> "FactorIndicator":
        """Construct one native factor with explicit target/input separation."""
        cls._validate_bind_request(datas)
        selected_mode = cls._resolve_factor_mode(mode)
        if "mode" in params:
            raise ResearchConfigError("factor mode must be passed as a FactorSpec or bind argument")
        resolved_factor_params = cls._resolve_factor_params(params)
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
            "mode": selected_mode,
            "factor_params": resolved_factor_params,
        }
        from .strict import live_source_binding_active

        runtime["live_source_binding"] = live_source_binding_active()
        context = None
        if strict and factor_name:
            context = FactorComputationContext(str(factor_name), phase="construct")
            for data in input_datas:
                asset = asset_by_data_id.get(id(data)) or getattr(data, "_name", None)
                if isinstance(asset, str) and asset:
                    context.bind_object(data, asset)
            runtime["strict_context"] = context
        bound_attributes: Dict[str, Any] = {
            "__module__": cls.__module__,
            "_factor_bound": True,
            "_mindatas": len(datas),
            "_factor_output_datas": targets,
            "_factor_output_names": output_names,
            "_factor_runtime": runtime,
            "lines": concrete_lines,
        }
        if selected_mode == "build":

            def build_mode_init(self: "FactorIndicator", *args: Any, **kwargs: Any) -> None:
                # Expression construction owns the bound instance lifecycle.
                # The author initializer belongs exclusively to native mode.
                FactorIndicator.__init__(self)

            # Keep every execution entry point inside the shared expression
            # lifecycle. Native callbacks and once implementations stay on the
            # original class and are selected only by native bindings.
            bound_attributes.update(
                {
                    "__init__": build_mode_init,
                    "prenext": FactorIndicator.prenext,
                    "nextstart": FactorIndicator.nextstart,
                    "next": FactorIndicator.next,
                    "preonce": Indicator.preonce_via_prenext,
                    "oncestart": Indicator.oncestart_via_nextstart,
                    "once": Indicator.once_via_next,
                }
            )

        bound_class = type(
            "_Bound_%s" % cls.__name__,
            (cls,),
            bound_attributes,
        )
        if context is not None:
            cls._validate_bound_sources(context, input_datas, targets, field_bindings)
            context.phase = "init"
        try:
            instance = bound_class(*datas, **resolved_factor_params)
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
        cls._validate_factor_declaration()
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
        index = self._factor_call_count
        if self._factor_once_range_count:
            raise RuntimeError("factor next() ran after its once coverage began")
        if self._factor_grid is not None:
            if index >= len(self._factor_grid):
                raise RuntimeError("factor next() ran more than once for the requested grid")
            if current != self._factor_grid[index]:
                raise RuntimeError("factor next() time does not match its next UTC grid point")
        self._factor_call_times.append(current)
        self._factor_call_count += 1

    def _record_factor_once(self, start: int, end: int) -> None:
        """Record a completed ordinary-once range without inventing next calls."""
        if start == end:
            return
        if type(start) is not int or type(end) is not int or start < 0 or end < start:
            raise RuntimeError("factor once() reported an invalid coverage range")
        covered = self._factor_call_count + self._factor_once_covered_count
        if start != covered:
            raise RuntimeError("factor once() left a gap or overlap in calculation-grid coverage")
        if self._factor_grid is not None and end > len(self._factor_grid):
            raise RuntimeError("factor once() covered beyond the requested calculation grid")
        self._factor_once_ranges.append((start, end))
        self._factor_once_range_count += 1
        self._factor_once_covered_count += end - start

    @property
    def lifecycle_diagnostics(self) -> Dict[str, Any]:
        """Read-only count and UTC-grid observations for lifecycle acceptance."""
        calls = tuple(self._factor_call_times)
        once_ranges = tuple(self._factor_once_ranges)
        if self._factor_live_bounded_diagnostics:
            coverage_count = self._factor_call_count + self._factor_once_covered_count
            return {
                "diagnostic_kind": "bounded_live_samples",
                "sample_limit": _LIVE_FACTOR_DIAGNOSTIC_SAMPLE_LIMIT,
                "call_count": self._factor_call_count,
                "call_times": calls,
                "call_times_truncated": self._factor_call_count > len(calls),
                "grid_count": None,
                "grid_matches": None,
                "next_count": self._factor_call_count,
                "next_times": calls,
                "once_ranges": once_ranges,
                "once_ranges_truncated": self._factor_once_range_count > len(once_ranges),
                "once_count": self._factor_once_covered_count,
                "once_times": (),
                "coverage_count": coverage_count,
                "coverage_times": calls,
                "coverage_times_truncated": coverage_count > len(calls),
                "coverage_matches": None,
            }
        grid = self._factor_grid
        once_count = sum(end - start for start, end in once_ranges)
        once_times = (
            tuple(value for start, end in once_ranges for value in grid[start:end])
            if grid is not None
            else ()
        )
        coverage_times = calls + once_times
        coverage_matches = bool(grid is not None and coverage_times == grid)
        return {
            "call_count": len(calls),
            "call_times": calls,
            "grid_count": len(grid or ()),
            "grid_matches": bool(grid is not None and calls == grid),
            "next_count": len(calls),
            "next_times": calls,
            "once_ranges": once_ranges,
            "once_count": once_count,
            "once_times": once_times,
            "coverage_count": len(calls) + once_count,
            "coverage_times": coverage_times,
            "coverage_matches": coverage_matches,
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
    def factor_mode(self) -> str:
        """The immutable native/build mode selected for this bound instance."""
        return cast(str, self._factor_runtime["mode"])

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
        raise ResearchConfigError(
            "field %s requires an explicit feed:<name>:<line> binding" % alias
        )


__all__ = ("FactorIndicator",)
