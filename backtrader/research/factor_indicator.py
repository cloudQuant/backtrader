"""Native Backtrader indicators with one real output line per input feed."""

from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, Mapping, Tuple

from .. import Indicator
from ..utils import num2date


class _OutputLines:
    """Attribute and item access to one feed's real indicator output lines."""

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


class FactorIndicator(Indicator):
    """Base class for multi-feed research factors.

    Concrete factors declare Backtrader line templates, implement ``next`` and
    use the usual ``__init__``/``super().__init__()`` pattern for native child
    indicators. Construct concrete factors through :meth:`bind`; it creates a private Backtrader Indicator
    subclass with the right ``_mindatas`` and a real line for every feed and
    template. Factor computation then runs on Backtrader's ordinary lifecycle.
    """

    lines = ()
    params = ()
    aliased = True
    panel_mode = "next"

    def __init__(self) -> None:
        if not getattr(self.__class__, "_factor_bound", False):
            raise TypeError("FactorIndicator instances must be created through bind()")

        self.outputs = {}
        self._factor_call_times = []
        self._factor_grid = None
        output_names = self.__class__._factor_output_names
        if len(self.datas) != len(output_names):
            raise RuntimeError("bound factor inputs do not match its output-line layout")

        for data, names in zip(self.datas, output_names):
            feed_lines = {}
            for template, alias in names:
                line = getattr(self.lines, alias)
                if not hasattr(line, "array") or not hasattr(line, "advance"):
                    raise RuntimeError("factor output is not a Backtrader line")
                feed_lines[template] = line
            self.outputs[data] = _OutputLines(feed_lines)

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

        super().__init_subclass__(**kwargs)
        if is_bound:
            return

        next_impl = cls.__dict__.get("next")
        if next_impl is not None and not getattr(next_impl, "_factor_counted", False):

            @wraps(next_impl)
            def counted_next(self, *args: Any, **next_kwargs: Any) -> Any:
                self._record_factor_call()
                return next_impl(self, *args, **next_kwargs)

            counted_next._factor_counted = True
            cls.next = counted_next

    def prenext(self) -> None:
        """Calculate during warm-up so the output lines contain real NaNs."""
        self.next()

    def nextstart(self) -> None:
        """Use the same calculation at the first bar meeting minperiod."""
        self.next()

    def next(self) -> None:
        raise NotImplementedError("concrete factor classes must implement next()")

    @classmethod
    def bind(cls, *datas: Any, **params: Any) -> "FactorIndicator":
        """Create a private concrete Indicator subclass bound to all feeds."""
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

        templates = cls._factor_template_names()
        if not templates:
            raise TypeError("factor class has no output-line templates")
        output_names = tuple(
            tuple((template, "asset_%d__%s" % (asset_index, template)) for template in templates)
            for asset_index in range(len(datas))
        )
        concrete_lines = tuple(alias for per_feed in output_names for _, alias in per_feed)
        bound_class = type(
            "_Bound_%s" % cls.__name__,
            (cls,),
            {
                "__module__": cls.__module__,
                "_factor_bound": True,
                "_mindatas": len(datas),
                "_factor_output_names": output_names,
                "lines": concrete_lines,
            },
        )
        instance = bound_class(*datas, **params)
        if not hasattr(instance, "outputs"):
            raise RuntimeError(
                "factor __init__ must call super().__init__() before creating child indicators"
            )
        if len(instance.datas) != len(datas) or any(
            actual is not expected for actual, expected in zip(instance.datas, datas)
        ):
            raise RuntimeError("Backtrader did not bind the requested factor feeds")
        if len(instance.outputs) != len(datas):
            raise RuntimeError("factor output-line binding is incomplete")
        return instance

    @classmethod
    def _factor_template_names(cls) -> Tuple[str, ...]:
        lines = getattr(cls, "lines", ())
        if hasattr(lines, "getlinealiases"):
            names = tuple(lines.getlinealiases())
        elif isinstance(lines, (tuple, list)):
            names = tuple(lines)
        else:
            names = ()
        # The concrete class may inherit the empty FactorIndicator template set.
        return tuple(name for name in names if isinstance(name, str) and name)

    def _bind_grid(self, grid: Tuple[datetime, ...]) -> None:
        """Attach and propagate the strategy's UTC grid through native factors."""
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
        if not self.datas:
            raise RuntimeError("factor next() has no data clock")
        current = num2date(float(self.datas[0].datetime[0]), tz=timezone.utc, naive=False)
        index = len(self._factor_call_times)
        if self._factor_grid is not None:
            if index >= len(self._factor_grid):
                raise RuntimeError("factor next() ran more than once for the requested grid")
            if current != self._factor_grid[index]:
                raise RuntimeError("factor next() time does not match its next UTC grid point")
        self._factor_call_times.append(current)

    @property
    def lifecycle_diagnostics(self) -> Dict[str, Any]:
        """Return compact call-count and UTC-grid diagnostics for R0 checks."""
        calls = tuple(self._factor_call_times)
        grid = self._factor_grid
        return {
            "call_count": len(calls),
            "call_times": calls,
            "grid_count": len(grid or ()),
            "grid_matches": bool(grid is not None and calls == grid),
        }

    def output_for(self, data: Any, line: str = "factor") -> Any:
        """Return the actual Backtrader output line for a feed and template."""
        try:
            return self.outputs[data][line]
        except KeyError as exc:
            raise KeyError("unknown factor feed or output template") from exc
