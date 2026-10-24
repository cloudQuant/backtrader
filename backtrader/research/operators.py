"""Native alpha101-v2 research operators.

This module provides a small, explicit operator vocabulary for formula authors.
It is deliberately not an expression parser or a second scheduler: scalar nodes
are ordinary Backtrader Indicators and panel nodes use :class:`FactorIndicator`
so their inputs, owner, clock, minperiod and once-via-next behavior remain in the
normal Indicator tree.

Every node has a ``value`` line and a numeric ``reason`` line.  Reason values
are the :class:`OperatorReason` enum values.  NaN is the numerical representation
of a missing or mathematically invalid value; infinities in source lines are
rejected because they are not a valid alpha101-v2 input.

Panel nodes accept one source line per bound feed through ``values=`` and return
one real output line per feed as ``node.outputs[data].value``.  Panel membership
is optional and is supplied as one Boolean/numeric line per feed; known false
members are excluded, while unknown membership is rejected.  ``IndNeutralize``
takes ordinary feed category lines through ``groups=`` (or reads the requested
``level`` line from each feed).
"""

import array as _array_module
from enum import IntEnum
import math
import numbers
import operator
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import Indicator
from ..linebuffer import LineBuffer
from ..feeds.pandafeed import PandasData
from ..lineseries import Lines
from .factor_indicator import (
    FactorIndicator,
    _PresenceLine,
    _factor_once_execute,
    _factor_once_write,
)


class OperatorReason(IntEnum):
    """Reason codes carried on each operator's ``reason`` line."""

    READY = 0
    NOT_READY = 1
    INCOMPLETE_WINDOW = 2
    NONFINITE_INPUT = 3
    DOMAIN_ERROR = 4
    UNKNOWN = 5
    UNKNOWN_CLASSIFICATION = 6
    FORMULA_INELIGIBLE = 7


REASON_NAMES = {int(reason): reason.name for reason in OperatorReason}


class OperatorInputError(ValueError):
    """Raised for invalid operator declarations or non-finite source values."""


_NAN = float("nan")
_LEVELS = ("sector", "industry", "subindustry")
_FAST_WINDOW_MISS = object()

# The window reader may bypass scalar ``LineBuffer.__getitem__`` calls only
# while the standard implementation is still installed. Keep these identities
# at import time so runtime monkeypatches take the established scalar path.
_LINEBUFFER_GETATTRIBUTE = LineBuffer.__getattribute__
_LINEBUFFER_GETITEM = LineBuffer.__getitem__
_LINEBUFFER_SETITEM = LineBuffer.__setitem__
_LINEBUFFER_LEN = LineBuffer.__len__
_LINEBUFFER_UNBOUNDED = LineBuffer.UnBounded
_LINEBUFFER_GETATTR = getattr(LineBuffer, "__getattr__", None)
_PANDASDATA_BUFLEN = getattr(PandasData, "buflen", None)
_PANDASDATA_ADVANCE = PandasData.advance
_PANDASDATA_TICK_NULLIFY = PandasData._tick_nullify
_PANDASDATA_TICK_FILL = PandasData._tick_fill
_PANDASDATA_GETATTRIBUTE = PandasData.__getattribute__
_PANDASDATA_GETATTR = getattr(PandasData, "__getattr__", None)
_PRESENCE_LINE_GETATTRIBUTE = _PresenceLine.__getattribute__
_PRESENCE_LINE_GETATTR = getattr(_PresenceLine, "__getattr__", None)
_LINES_GETATTRIBUTE = Lines.__getattribute__
_LINES_GETATTR = getattr(Lines, "__getattr__", None)
_LINES_BUFLEN = Lines.buflen


def _qbuffer_logical_to_physical(line: Any, logical_index: int) -> Optional[int]:
    """Map a populated grid index into one queued line's retained tail."""
    if logical_index < 0:
        return None
    try:
        source_array = line.array
        logical_length = int(line.lencount)
        extension = int(line.extension)
        retained_length = len(source_array) - extension
    except (AttributeError, TypeError, ValueError):
        return None
    if logical_length <= logical_index or retained_length < 0:
        return None

    logical_origin = logical_length - retained_length
    physical_index = logical_index - logical_origin
    if physical_index < 0 or physical_index >= retained_length:
        return None
    return physical_index


def _associated_reason(
    source: Any, *, ago: int = 0, absolute_index: Optional[int] = None
) -> Optional[OperatorReason]:
    """Read a producer's marked reason line at the same value grid slot."""
    reason_line = getattr(source, "_factor_research_reason_line", None)
    if reason_line is None:
        line_owner = getattr(source, "_owner", None)
        indicator = getattr(line_owner, "_owner_ref", None)
        if indicator is None:
            indicator = getattr(line_owner, "_owner", None)
        outputs = getattr(indicator, "outputs", None)
        factor_targets = getattr(indicator, "_factor_target_datas", ())
        if outputs is not None:
            for target in factor_targets:
                try:
                    output_lines = outputs[target]._lines
                except (KeyError, AttributeError):
                    continue
                if output_lines.get("value") is source:
                    reason_line = output_lines.get("reason")
                    break
        if reason_line is None and getattr(indicator, "_operand_args", None) is not None:
            lines = getattr(indicator, "lines", None)
            if getattr(lines, "value", None) is source:
                reason_line = getattr(lines, "reason", None)
    if reason_line is None or reason_line is source:
        return None
    try:
        if absolute_index is None:
            raw_reason = float(reason_line[ago])
        else:
            try:
                reason_mode = reason_line.mode
            except AttributeError:
                reason_mode = LineBuffer.UnBounded
            if reason_mode != LineBuffer.QBuffer:
                if absolute_index < 0 or absolute_index >= reason_line.lencount:
                    return None
                physical_index = absolute_index
            else:
                physical_index = _qbuffer_logical_to_physical(reason_line, absolute_index)
            if physical_index is None:
                return None
            raw_reason = float(reason_line.array[physical_index])
        if not math.isfinite(raw_reason) or raw_reason != int(raw_reason):
            return None
        reason = OperatorReason(int(raw_reason))
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    return reason if reason is not OperatorReason.READY else None


def _floor_window(value: Any, name: str, allow_zero: bool = False) -> int:
    """Validate a finite scalar window and apply alpha101-v2 floor semantics."""
    if isinstance(value, bool):
        raise ValueError("%s must be a finite non-boolean number" % name)
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must be a finite non-boolean number" % name) from exc
    if not math.isfinite(numeric):
        raise ValueError("%s must be finite" % name)
    result = math.floor(numeric)
    minimum = 0 if allow_zero else 1
    if result < minimum:
        raise ValueError("floor(%s) must be >= %d" % (name, minimum))
    return result


def _read_value(source: Any, ago: int = 0) -> Tuple[float, OperatorReason]:
    """Read one currently available line value without hiding source errors."""
    if source is None:
        return _NAN, OperatorReason.NONFINITE_INPUT
    if len(source) <= abs(ago):
        return _NAN, OperatorReason.NOT_READY
    # LineBuffer.__getitem__ preserves a legacy infinity-to-zero fallback
    # outside FactorIndicator's strict scope. Inspect the same physical slot
    # first so the alpha101 operator contract can reject source infinities in
    # both ordinary and strict research runs.
    raw_index = None
    source_length = None
    try:
        source_index = source._idx
        source_length = source.lencount
        if source_length > 0 and source_index >= source_length:
            source_index = source_length - 1
        raw_index = source_index + ago
        raw_value = source.array[raw_index]
    except (AttributeError, IndexError, TypeError):
        raw_value = None
    if raw_value is not None and math.isinf(float(raw_value)):
        raise OperatorInputError("source line contains infinity")
    value = float(source[ago])
    if math.isinf(value):
        raise OperatorInputError("source line contains infinity")
    if math.isnan(value):
        reason_index = raw_index
        try:
            if source.mode == LineBuffer.QBuffer and source_length is not None:
                reason_index = source_length - 1 + ago
        except AttributeError:
            pass
        reason = _associated_reason(source, absolute_index=reason_index)
        return _NAN, reason or OperatorReason.NONFINITE_INPUT
    return value, OperatorReason.READY


def _read_operand(source: Any, ago: int = 0) -> Tuple[float, OperatorReason]:
    """Read a line operand or a literal without manufacturing a line node."""
    if isinstance(source, bool):
        raise OperatorInputError("operator scalar inputs must be non-boolean real numbers")
    if isinstance(source, numbers.Real):
        value = float(source)
        if math.isinf(value):
            raise OperatorInputError("scalar operator input contains infinity")
        if math.isnan(value):
            return _NAN, OperatorReason.NONFINITE_INPUT
        return value, OperatorReason.READY
    return _read_value(source, ago)


def _try_read_unbounded_linebuffer_window(source: Any, period: int) -> Any:
    """Read a safe contiguous LineBuffer window, or return the miss sentinel.

    This narrow path is limited to the exact standard LineBuffer storage and
    method implementations. It reads the current array on every call, so a
    normal reset that replaces the backing array cannot leave stale data in a
    cache. Every other source retains the scalar reader's existing behavior.
    """
    if type(source) is not LineBuffer or type(period) is not int or period <= 0:
        return _FAST_WINDOW_MISS
    if (
        LineBuffer.__getattribute__ is not _LINEBUFFER_GETATTRIBUTE
        or LineBuffer.__getitem__ is not _LINEBUFFER_GETITEM
        or LineBuffer.__len__ is not _LINEBUFFER_LEN
    ):
        return _FAST_WINDOW_MISS

    index = source._idx
    logical_length = source.lencount
    mode = source.mode
    storage = source.array
    if (
        type(index) is not int
        or type(logical_length) is not int
        or type(mode) is not int
        or mode != _LINEBUFFER_UNBOUNDED
        or type(storage) is not _array_module.array
        or storage.typecode != "d"
        or logical_length < period
    ):
        return _FAST_WINDOW_MISS

    if logical_length > 0 and index >= logical_length:
        index = logical_length - 1
    start = index - period + 1
    stop = index + 1
    if start < 0 or stop > len(storage) or stop - start != period:
        return _FAST_WINDOW_MISS

    # array.array slicing returns a fresh array('d') snapshot. Keep the old
    # oldest-to-newest validation order and do not alter the downstream math.
    values = []
    for offset, raw_value in enumerate(storage[start:stop]):
        # Exact array('d') indexing yields a builtin float, so the scalar
        # reader's repeated float conversion and infinity check are redundant.
        if math.isinf(raw_value):
            raise OperatorInputError("source line contains infinity")
        if math.isnan(raw_value):
            # The window result is always INCOMPLETE_WINDOW, but preserve the
            # scalar reader's reason lookup and its observable failures.
            _associated_reason(source, absolute_index=start + offset)
            return None, OperatorReason.INCOMPLETE_WINDOW
        values.append(raw_value)
    return values, OperatorReason.READY


def _read_window(source: Any, period: int) -> Tuple[Optional[List[float]], OperatorReason]:
    """Read a complete oldest-to-newest window, preserving every grid slot."""
    if not isinstance(source, numbers.Real) and len(source) < period:
        return None, OperatorReason.NOT_READY
    fast_result = _try_read_unbounded_linebuffer_window(source, period)
    if fast_result is not _FAST_WINDOW_MISS:
        return fast_result
    values = []
    for ago in range(period - 1, -1, -1):
        value, reason = _read_operand(source, -ago)
        if reason is not OperatorReason.READY:
            return None, OperatorReason.INCOMPLETE_WINDOW
        values.append(value)
    return values, OperatorReason.READY


def _result(value: Any) -> Tuple[float, OperatorReason]:
    """Check an arithmetic result, classifying known non-finite results as domain errors."""
    result = float(value)
    if not math.isfinite(result):
        return _NAN, OperatorReason.DOMAIN_ERROR
    return result, OperatorReason.READY


def _guarded_result(operation: Any) -> Tuple[float, OperatorReason]:
    """Turn expected floating-domain failures into the contract's NaN result."""
    try:
        return _result(operation())
    except (OverflowError, ValueError, ZeroDivisionError):
        return _NAN, OperatorReason.DOMAIN_ERROR


def _stable_mean(values: Sequence[float]) -> float:
    """Compute a mean without overflowing an intermediate finite sum."""
    scale = max((abs(value) for value in values), default=0.0)
    if scale == 0.0:
        return 0.0
    return scale * (math.fsum(value / scale for value in values) / len(values))


def _is_line_operand(value: Any) -> bool:
    """Check for a Backtrader line without treating numeric scalars as lines."""
    if isinstance(value, numbers.Real):
        return False
    try:
        value.array
        return True
    except AttributeError:
        try:
            value.lines
            return True
        except AttributeError:
            return False


def _stable_product(values: Sequence[float]) -> float:
    """Multiply finite values without a false intermediate overflow."""
    negative = sum(math.copysign(1.0, value) < 0.0 for value in values) % 2 == 1
    if any(value == 0.0 for value in values):
        return -0.0 if negative else 0.0

    mantissa = 1.0
    exponent = 0
    for value in values:
        part, part_exponent = math.frexp(abs(value))
        mantissa *= part
        exponent += part_exponent
        mantissa, adjustment = math.frexp(mantissa)
        exponent += adjustment
    result = math.ldexp(-mantissa if negative else mantissa, exponent)
    return result


def _average_rank(values: Sequence[float]) -> List[float]:
    """Return average ranks divided by the finite population size."""
    count = len(values)
    if not count:
        return []
    order = sorted(range(count), key=lambda index: values[index])
    result = [0.0] * count
    start = 0
    while start < count:
        end = start + 1
        while end < count and values[order[end]] == values[order[start]]:
            end += 1
        rank = ((start + 1) + end) / 2.0 / count
        for offset in range(start, end):
            result[order[offset]] = rank
        start = end
    return result


def _target_clock_line(data: Any) -> Any:
    """Return a target feed's first real line as its current grid clock."""
    lines = getattr(getattr(data, "lines", None), "lines", None)
    if not lines:
        raise OperatorInputError("panel target has no clock line")
    return lines[0]


def _clock_matches_target(clock: Any, target: Any, seen: Optional[set] = None) -> bool:
    """Resolve simple native line clocks and require the bound target feed."""
    if clock is target:
        return True
    if clock is None:
        return False
    if seen is None:
        seen = set()
    if id(clock) in seen:
        return False
    seen.add(id(clock))
    target_lines = getattr(getattr(target, "lines", None), "lines", ())
    if any(clock is line for line in target_lines):
        return True
    return _clock_matches_target(getattr(clock, "_clock", None), target, seen)


def _line_target_relation(source: Any, target: Any, seen: Optional[set] = None) -> Optional[bool]:
    """Resolve a line's target when its native owner clock is shared.

    A multi-output FactorIndicator has one native owner clock, while its output
    lines are individually associated with different target feeds. Scalar
    nodes built from one of those output lines inherit the shared owner clock,
    so clock identity alone cannot distinguish the target for later feeds.
    """
    target_lines = getattr(getattr(target, "lines", None), "lines", ())
    if source is target or any(source is line for line in target_lines):
        return True

    marker = getattr(source, "_factor_research_target", None)
    if marker is not None:
        return marker is target

    if seen is None:
        seen = set()
    if id(source) in seen:
        return None
    seen.add(id(source))

    line_owner = getattr(source, "_owner", None)
    indicator = getattr(line_owner, "_owner_ref", None)
    if indicator is None:
        indicator = getattr(line_owner, "_owner", None)
    if indicator is None:
        return None

    outputs = getattr(indicator, "outputs", None)
    factor_targets = getattr(indicator, "_factor_target_datas", ())
    if outputs is not None:
        for output_target in factor_targets:
            try:
                output_lines = outputs[output_target]._lines.values()
            except (KeyError, AttributeError):
                continue
            if any(source is line for line in output_lines):
                return output_target is target

    operands = getattr(indicator, "_operand_args", None)
    if operands is not None:
        dependencies = [operand for operand in operands if _is_line_operand(operand)]
        if (
            not dependencies
            and isinstance(indicator, _OperatorIndicator)
            and operands
            and all(
                isinstance(operand, numbers.Real) and not isinstance(operand, bool)
                for operand in operands
            )
        ):
            # A scalar-only native operator is a target-neutral leaf.  It may
            # participate in an otherwise target-bound expression without
            # obscuring the feed identity carried by its sibling operands.
            return True
        if dependencies:
            # ``seen`` is a recursion path, not a global visited set. Scalar
            # expressions commonly form a DAG where sibling branches share an
            # input line; revisiting that line on the second branch must still
            # resolve its target instead of degrading the whole relation to
            # unknown.
            relations = [
                _line_target_relation(dependency, target, seen.copy())
                for dependency in dependencies
            ]
            if any(relation is False for relation in relations):
                return False
            if all(relation is True for relation in relations):
                return True

    datas = getattr(indicator, "datas", ())
    if datas:
        relations = []
        for data in datas:
            if data is target or any(data is line for line in target_lines):
                relations.append(True)
                continue
            relations.append(_line_target_relation(data, target, seen.copy()))
        if any(relation is False for relation in relations):
            return False
        if relations and all(relation is True for relation in relations):
            return True
    return None


_PANEL_RELATION_MISS = object()


def _relation_instance_dict(instance: Any) -> Optional[dict]:
    """Read an ordinary instance dictionary without invoking dynamic lookup."""
    try:
        state = object.__getattribute__(instance, "__dict__")
    except (AttributeError, TypeError):
        return None
    return state if type(state) is dict else None


def _standard_presence_relation_classes() -> bool:
    """Keep the shortcut on the standard line/feed/indicator implementations."""
    return (
        LineBuffer.__getattribute__ is _LINEBUFFER_GETATTRIBUTE
        and getattr(LineBuffer, "__getattr__", None) is _LINEBUFFER_GETATTR
        and PandasData.__getattribute__ is _PANDASDATA_GETATTRIBUTE
        and getattr(PandasData, "__getattr__", None) is _PANDASDATA_GETATTR
        and _PresenceLine.__getattribute__ is _PRESENCE_LINE_GETATTRIBUTE
        and getattr(_PresenceLine, "__getattr__", None) is _PRESENCE_LINE_GETATTR
        and Lines.__getattribute__ is _LINES_GETATTRIBUTE
        and getattr(Lines, "__getattr__", None) is _LINES_GETATTR
    )


def _standard_lines_instance(instance: Any) -> bool:
    cls = type(instance)
    return (
        isinstance(instance, Lines)
        and cls.__getattribute__ is _LINES_GETATTRIBUTE
        and getattr(cls, "__getattr__", None) is _LINES_GETATTR
    )


class _PresenceLineRelationPlan:
    """Live-guarded proof for an ordinary presence line on its own feed."""

    __slots__ = (
        "source", "target", "owner", "indicator", "datas", "owner_lines",
    )

    def __init__(self, source: Any, target: Any, owner: Any, indicator: Any,
                 datas: list, owner_lines: list) -> None:
        self.source = source
        self.target = target
        self.owner = owner
        self.indicator = indicator
        self.datas = datas
        self.owner_lines = owner_lines

    @classmethod
    def bind(cls, source: Any, target: Any) -> Optional["_PresenceLineRelationPlan"]:
        """Bind only the exact native presence-line/feed ownership shape."""
        if (not _standard_presence_relation_classes()
                or type(source) is not LineBuffer or type(target) is not PandasData):
            return None
        source_state = _relation_instance_dict(source)
        target_state = _relation_instance_dict(target)
        if (source_state is None or target_state is None
                or source_state.get("_factor_research_target") is not None
                or target_state.get("_factor_research_target") is not None):
            return None

        owner = source_state.get("_owner")
        if (type(owner) is not _PresenceLine.lines
                or not _standard_lines_instance(owner)):
            return None
        owner_state = _relation_instance_dict(owner)
        if owner_state is None:
            return None
        indicator = owner_state.get("_owner_ref")
        if type(indicator) is not _PresenceLine:
            return None
        indicator_state = _relation_instance_dict(indicator)
        if indicator_state is None:
            return None
        datas = indicator_state.get("datas")
        owner_lines = owner_state.get("lines")
        if (type(datas) is not list or len(datas) != 1 or datas[0] is not target
                or type(owner_lines) is not list or not any(line is source for line in owner_lines)
                or indicator_state.get("outputs") is not None
                or indicator_state.get("_operand_args") is not None):
            return None
        return cls(source, target, owner, indicator, datas, owner_lines)

    def resolve(self, source: Any, target: Any) -> Any:
        """Return the proven relation, or ask the ordinary resolver instead."""
        if (source is not self.source or target is not self.target
                or type(source) is not LineBuffer or type(target) is not PandasData
                or type(self.owner) is not _PresenceLine.lines
                or not _standard_lines_instance(self.owner)
                or type(self.indicator) is not _PresenceLine
                or not _standard_presence_relation_classes()):
            return _PANEL_RELATION_MISS
        source_state = _relation_instance_dict(source)
        target_state = _relation_instance_dict(target)
        owner_state = _relation_instance_dict(self.owner)
        indicator_state = _relation_instance_dict(self.indicator)
        if (source_state is None or target_state is None
                or owner_state is None or indicator_state is None):
            return _PANEL_RELATION_MISS
        if (source_state.get("_owner") is not self.owner
                or source_state.get("_factor_research_target") is not None
                or target_state.get("_factor_research_target") is not None
                or owner_state.get("_owner_ref") is not self.indicator
                or owner_state.get("lines") is not self.owner_lines
                or not any(line is source for line in self.owner_lines)
                or indicator_state.get("datas") is not self.datas
                or type(self.datas) is not list or len(self.datas) != 1
                or self.datas[0] is not target
                or indicator_state.get("outputs") is not None
                or indicator_state.get("_operand_args") is not None):
            return _PANEL_RELATION_MISS
        return True


def _presence_line_relation_plan(
    source: Any, target: Any
) -> Optional[_PresenceLineRelationPlan]:
    return _PresenceLineRelationPlan.bind(source, target)


def _resolve_panel_relation(
    source: Any, target: Any, relation_plan: Optional[_PresenceLineRelationPlan] = None
) -> Optional[bool]:
    if relation_plan is not None:
        relation = relation_plan.resolve(source, target)
        if relation is not _PANEL_RELATION_MISS:
            return relation
    return _line_target_relation(source, target)


def _panel_value_array(
    source: Any,
    target: Any,
    grid_index: int,
    relation_plan: Optional[_PresenceLineRelationPlan] = None,
) -> Tuple[Optional[Any], Optional[int], OperatorReason, bool]:
    """Resolve a target-aligned value array and its current physical slot."""
    if source is None:
        return None, None, OperatorReason.NONFINITE_INPUT, False
    try:
        source_array = source.array
    except AttributeError as exc:
        raise OperatorInputError("panel values, membership and groups must be lines") from exc
    try:
        source_is_qbuffer = source.mode == LineBuffer.QBuffer
    except AttributeError:
        source_is_qbuffer = False

    target_line = _target_clock_line(target)
    if grid_index < 0 or target_line.lencount <= grid_index:
        return None, None, OperatorReason.NOT_READY, source_is_qbuffer

    # A shared native owner clock cannot identify one of several panel output
    # lines. Prefer retained line provenance, then use the ordinary clock for
    # lines without inspectable target provenance.
    relation = _resolve_panel_relation(source, target, relation_plan)
    if relation is False:
        raise OperatorInputError("panel input line is bound to a different target feed")
    if relation is not True:
        source_owner = getattr(source, "_owner", None)
        source_clock = getattr(source, "_clock", None)
        if source_clock is None and source_owner is not None:
            source_clock = getattr(source_owner, "_clock", None)
        if not _clock_matches_target(source_clock, target):
            raise OperatorInputError("panel input clock does not match its target feed")

    # In vectorized mode a child indicator can have populated its full result
    # array while its line cursor remains at -1. The target grid index is
    # authoritative after provenance/clock validation above.
    if source_is_qbuffer:
        physical_index = _qbuffer_logical_to_physical(source, grid_index)
        if physical_index is None:
            return None, None, OperatorReason.NOT_READY, True
    else:
        if grid_index >= len(source_array):
            return None, None, OperatorReason.NOT_READY, False
        physical_index = grid_index
    return source_array, physical_index, OperatorReason.READY, source_is_qbuffer


def _read_panel_value_at(
    source: Any,
    target: Any,
    grid_index: int,
    relation_plan: Optional[_PresenceLineRelationPlan] = None,
) -> Tuple[float, OperatorReason]:
    """Read one panel parameter at an absolute target-grid index."""
    source_array, physical_index, readiness, _ = _panel_value_array(
        source, target, grid_index, relation_plan=relation_plan
    )
    if source_array is None:
        return _NAN, readiness
    if physical_index is None:
        return _NAN, OperatorReason.NOT_READY
    raw = float(source_array[physical_index])
    if math.isinf(raw):
        raise OperatorInputError("panel input line contains infinity")
    if math.isnan(raw):
        reason = _associated_reason(source, absolute_index=grid_index)
        return _NAN, reason or OperatorReason.NONFINITE_INPUT
    return raw, OperatorReason.READY


def _read_panel_value(
    source: Any,
    target: Any,
    relation_plan: Optional[_PresenceLineRelationPlan] = None,
) -> Tuple[float, OperatorReason]:
    """Read a panel parameter at the target feed's populated current grid."""
    target_line = _target_clock_line(target)
    grid_index = int(target_line._idx)
    if target_line.mode == LineBuffer.QBuffer:
        grid_index = int(target_line.lencount) - 1
    return _read_panel_value_at(
        source, target, grid_index, relation_plan=relation_plan
    )


def _read_panel_window(
    source: Any, target: Any, period: int
) -> Tuple[Optional[List[float]], OperatorReason]:
    """Read a scalar-equivalent window by absolute target-grid indices.

    Panel inputs can be sibling indicators whose once-via-next pass has already
    filled the array and left its cursor at the final row. The target feed's
    current index therefore selects the window; the source cursor must not.
    """
    if isinstance(source, numbers.Real):
        return _read_window(source, period)

    target_line = _target_clock_line(target)
    grid_index = int(target_line._idx)
    if target_line.mode == LineBuffer.QBuffer:
        grid_index = int(target_line.lencount) - 1
    if grid_index < 0 or target_line.lencount <= grid_index:
        return None, OperatorReason.NOT_READY
    start = grid_index - period + 1
    if start < 0:
        return None, OperatorReason.NOT_READY

    source_array, _, readiness, source_is_qbuffer = _panel_value_array(
        source, target, grid_index
    )
    if source_array is None:
        return None, readiness
    values: List[float] = []
    for absolute_index in range(start, grid_index + 1):
        if source_is_qbuffer:
            physical_index = _qbuffer_logical_to_physical(source, absolute_index)
        else:
            physical_index = absolute_index
            if physical_index >= len(source_array):
                return None, OperatorReason.NOT_READY
        if physical_index is None:
            return None, OperatorReason.NOT_READY
        value = float(source_array[physical_index])
        if math.isinf(value):
            raise OperatorInputError("panel input line contains infinity")
        if math.isnan(value):
            # Scalar _read_window reads and classifies the producer reason, then
            # reports INCOMPLETE_WINDOW for any invalid slot in the window.
            _associated_reason(source, absolute_index=absolute_index)
            return None, OperatorReason.INCOMPLETE_WINDOW
        values.append(value)
    return values, OperatorReason.READY


def _line_pair_results(
    left_result: Tuple[float, OperatorReason], right_result: Tuple[float, OperatorReason]
) -> Tuple[float, float, OperatorReason]:
    left_value, left_reason = left_result
    right_value, right_reason = right_result
    if left_reason is OperatorReason.READY and right_reason is OperatorReason.READY:
        return left_value, right_value, OperatorReason.READY
    reasons = tuple(
        reason for reason in (left_reason, right_reason) if reason is not OperatorReason.READY
    )
    # Preserve concrete upstream diagnostics through pointwise arithmetic.
    # Generic source NaN is used only when no producer supplied a more useful
    # reason code; otherwise input order resolves multiple distinct failures.
    reason = next(
        (candidate for candidate in reasons if candidate is not OperatorReason.NONFINITE_INPUT),
        reasons[0],
    )
    return _NAN, _NAN, reason


def _line_pair(left: Any, right: Any) -> Tuple[float, float, OperatorReason]:
    return _line_pair_results(_read_operand(left), _read_operand(right))


def _read_panel_operand(source: Any, target: Any) -> Tuple[float, OperatorReason]:
    if isinstance(source, numbers.Real):
        return _read_operand(source)
    return _read_panel_value(source, target)


class _OperatorIndicator(Indicator):
    """Base class for scalar native operator nodes."""

    lines: Any = ("value", "reason")
    _mindatas = 1
    _operator_input_count = 1

    def __init__(self) -> None:
        count = self._operator_input_count
        raw_args = tuple(getattr(self, "_init_args", ()))[:count]
        if len(raw_args) != count:
            raise TypeError("operator received the wrong number of inputs")

        line_inputs: List[Any] = []
        seen = set()
        for operand in raw_args:
            if _is_line_operand(operand):
                if id(operand) not in seen:
                    line_inputs.append(operand)
                    seen.add(id(operand))
            elif isinstance(operand, bool) or not isinstance(operand, numbers.Real):
                raise OperatorInputError("operator inputs must be lines or real scalar constants")
            elif math.isinf(float(operand)):
                raise OperatorInputError("scalar operator input contains infinity")

        # Preserve the original _init_args and feed the native LineIterator
        # only the identity-unique real dependencies.  Literal operands remain
        # Python numbers and never become both datas and child indicators.
        super().__init__(*line_inputs)
        self._operand_args = raw_args
        self.lines.value._factor_research_reason_line = self.lines.reason
        for index, operand in enumerate(raw_args):
            setattr(self, "data%d" % index, operand)
        self._period: Any = None

    def _operand(self, index: int) -> Any:
        return self._operand_args[index]

    def prenext(self) -> None:
        self.next()

    def nextstart(self) -> None:
        self.next()

    def next(self) -> None:
        value, reason = self._evaluate()
        self.lines.value[0] = value
        self.lines.reason[0] = float(reason)

    def _evaluate(self) -> Tuple[float, OperatorReason]:
        raise NotImplementedError


class _Unary(_OperatorIndicator):
    """Base for pointwise unary operations."""

    _apply: Any

    def _evaluate(self) -> Tuple[float, OperatorReason]:
        value, reason = _read_operand(self._operand(0))
        if reason is not OperatorReason.READY:
            return _NAN, reason
        try:
            return _result(self._apply(value))
        except (ValueError, ZeroDivisionError, OverflowError):
            return _NAN, OperatorReason.DOMAIN_ERROR


class _Binary(_OperatorIndicator):
    """Base for pointwise binary operations with line-or-scalar operands."""

    _mindatas = 2
    _operator_input_count = 2
    _apply: Any

    def _evaluate(self) -> Tuple[float, OperatorReason]:
        left, right, reason = _line_pair(self._operand(0), self._operand(1))
        if reason is not OperatorReason.READY:
            return _NAN, reason
        try:
            return _result(self._apply(left, right))
        except (ValueError, ZeroDivisionError, OverflowError):
            return _NAN, OperatorReason.DOMAIN_ERROR


class Add(_Binary):
    """Pointwise addition."""

    _apply = staticmethod(operator.add)


class Subtract(_Binary):
    """Pointwise subtraction."""

    _apply = staticmethod(operator.sub)


class Multiply(_Binary):
    """Pointwise multiplication."""

    _apply = staticmethod(operator.mul)


class Divide(_Binary):
    """Pointwise division; a zero denominator is DOMAIN_ERROR."""

    _apply = staticmethod(operator.truediv)


class Minimum(_Binary):
    """Pointwise ``min(x, y)``; rolling minimum is :class:`TsMin`."""

    _apply = staticmethod(min)


class Maximum(_Binary):
    """Pointwise ``max(x, y)``; rolling maximum is :class:`TsMax`."""

    _apply = staticmethod(max)


class Power(_Binary):
    """Ordinary real power, not XOR and not signed power."""

    _apply = staticmethod(math.pow)


class _Comparison(_Binary):
    def _evaluate(self) -> Tuple[float, OperatorReason]:
        left, right, reason = _line_pair(self._operand(0), self._operand(1))
        if reason is not OperatorReason.READY:
            return _NAN, OperatorReason.UNKNOWN
        return float(self._apply(left, right)), OperatorReason.READY


class LessThan(_Comparison):
    """Three-valued pointwise ``x < y`` returning 1, 0, or NaN."""

    _apply = staticmethod(operator.lt)


class LessEqual(_Comparison):
    """Three-valued pointwise ``x <= y`` returning 1, 0, or NaN."""

    _apply = staticmethod(operator.le)


class GreaterThan(_Comparison):
    """Three-valued pointwise ``x > y`` returning 1, 0, or NaN."""

    _apply = staticmethod(operator.gt)


class GreaterEqual(_Comparison):
    """Three-valued pointwise ``x >= y`` returning 1, 0, or NaN."""

    _apply = staticmethod(operator.ge)


class EqualTo(_Comparison):
    """Three-valued pointwise exact equality."""

    _apply = staticmethod(operator.eq)


class NotEqualTo(_Comparison):
    """Three-valued pointwise exact inequality."""

    _apply = staticmethod(operator.ne)


class Abs(_Unary):
    """Pointwise absolute value."""

    _apply = staticmethod(abs)


class Sign(_Unary):
    """Pointwise sign with ``sign(0) == 0``."""

    @staticmethod
    def _apply(value: float) -> float:
        return float((value > 0.0) - (value < 0.0))


class Log(_Unary):
    """Natural logarithm; non-positive values are DOMAIN_ERROR."""

    _apply = staticmethod(math.log)


class Sqrt(_Unary):
    """Principal square root; negative values are DOMAIN_ERROR."""

    _apply = staticmethod(math.sqrt)


class Negate(_Unary):
    """Pointwise negation."""

    _apply = staticmethod(operator.neg)


class SignedPower(_Binary):
    """``sign(x) * abs(x) ** a`` with an expression-valued exponent."""

    @staticmethod
    def _apply(value: float, exponent: float) -> float:
        if value == 0.0:
            if exponent < 0.0:
                raise ValueError("zero to a negative signed power")
            return 0.0
        return math.copysign(math.pow(abs(value), exponent), value)


class Where(_OperatorIndicator):
    """Three-input conditional; only the selected branch controls validity."""

    _mindatas = 3
    _operator_input_count = 3

    def _evaluate(self) -> Tuple[float, OperatorReason]:
        condition, condition_reason = _read_operand(self._operand(0))
        if condition_reason is not OperatorReason.READY:
            return _NAN, OperatorReason.UNKNOWN
        if condition not in (0.0, 1.0):
            raise OperatorInputError("where condition must be a 0/1/unknown comparison")
        selected = self._operand(1) if condition == 1.0 else self._operand(2)
        value, reason = _read_operand(selected)
        return value, reason


class LogicalNot(_Unary):
    """Three-valued logical NOT over numeric Boolean values."""

    def _evaluate(self) -> Tuple[float, OperatorReason]:
        value, reason = _read_operand(self._operand(0))
        if reason is not OperatorReason.READY:
            return _NAN, OperatorReason.UNKNOWN
        if value not in (0.0, 1.0):
            raise OperatorInputError("logical input must be a 0/1/unknown value")
        return 1.0 - value, OperatorReason.READY


class _LogicalBinary(_Binary):
    def _evaluate(self) -> Tuple[float, OperatorReason]:
        left, left_reason = _read_operand(self._operand(0))
        right, right_reason = _read_operand(self._operand(1))
        left_known = left_reason is OperatorReason.READY
        right_known = right_reason is OperatorReason.READY
        if left_known and left not in (0.0, 1.0):
            raise OperatorInputError("logical input must be a 0/1/unknown value")
        if right_known and right not in (0.0, 1.0):
            raise OperatorInputError("logical input must be a 0/1/unknown value")
        return self._truth(left, left_known, right, right_known)

    def _truth(
        self, left: float, left_known: bool, right: float, right_known: bool
    ) -> Tuple[float, OperatorReason]:
        raise NotImplementedError


class LogicalAnd(_LogicalBinary):
    """Kleene three-valued AND."""

    def _truth(self, left, left_known, right, right_known):
        if (left_known and left == 0.0) or (right_known and right == 0.0):
            return 0.0, OperatorReason.READY
        if left_known and right_known:
            return 1.0, OperatorReason.READY
        return _NAN, OperatorReason.UNKNOWN


class LogicalOr(_LogicalBinary):
    """Kleene three-valued OR."""

    def _truth(self, left, left_known, right, right_known):
        if (left_known and left == 1.0) or (right_known and right == 1.0):
            return 1.0, OperatorReason.READY
        if left_known and right_known:
            return 0.0, OperatorReason.READY
        return _NAN, OperatorReason.UNKNOWN


class _Rolling(_OperatorIndicator):
    params: Any = (("period", 1),)

    def __init__(self) -> None:
        period = _floor_window(self.p.period, "period")
        super().__init__()
        self._period = period
        self.addminperiod(self._period)

    def _window(self, source: Any = None) -> Tuple[Optional[List[float]], OperatorReason]:
        return _read_window(source if source is not None else self._operand(0), self._period)


class Delay(_OperatorIndicator):
    """Read a value floor(period) grid rows earlier; period zero is current."""

    params: Any = (("period", 1),)
    _allow_zero_period = True

    def __init__(self) -> None:
        period = _floor_window(self.p.period, "period", allow_zero=self._allow_zero_period)
        super().__init__()
        self._period = period
        self.addminperiod(self._period + 1)

    def _evaluate(self) -> Tuple[float, OperatorReason]:
        return _read_operand(self._operand(0), -self._period)


class Delta(Delay):
    """Difference ``x[t] - x[t-floor(period)]`` on the explicit grid."""

    _allow_zero_period = False

    def __init__(self) -> None:
        super().__init__()

    def _evaluate(self) -> Tuple[float, OperatorReason]:
        current, current_reason = _read_operand(self._operand(0))
        prior, prior_reason = _read_operand(self._operand(0), -self._period)
        if current_reason is not OperatorReason.READY or prior_reason is not OperatorReason.READY:
            if OperatorReason.NOT_READY in (current_reason, prior_reason):
                return _NAN, OperatorReason.NOT_READY
            return _NAN, OperatorReason.NONFINITE_INPUT
        return _result(current - prior)


class RollingSum(_Rolling):
    """Sum a complete rolling grid window."""

    def _evaluate(self):
        values, reason = self._window()
        if values is None:
            return _NAN, reason
        return _guarded_result(lambda: math.fsum(values))


class RollingProduct(_Rolling):
    """Product of a complete rolling grid window."""

    def _evaluate(self):
        values, reason = self._window()
        if values is None:
            return _NAN, reason
        return _guarded_result(lambda: _stable_product(values))


class RollingMean(_Rolling):
    """Arithmetic mean of a complete rolling grid window."""

    def _evaluate(self):
        values, reason = self._window()
        if values is None:
            return _NAN, reason
        return _guarded_result(lambda: _stable_mean(values))


class RollingStd(_Rolling):
    """Population standard deviation (ddof=0) over a complete window."""

    def _evaluate(self):
        values, reason = self._window()
        if values is None:
            return _NAN, reason

        def calculate() -> float:
            scale = max(abs(value) for value in values)
            if scale == 0.0:
                return 0.0
            normalized = [value / scale for value in values]
            mean = _stable_mean(normalized)
            variance = math.fsum((value - mean) ** 2 for value in normalized) / self._period
            return scale * math.sqrt(variance)

        return _guarded_result(calculate)


class TsMin(_Rolling):
    """Rolling minimum; pointwise minimum is :class:`Minimum`."""

    def _evaluate(self):
        values, reason = self._window()
        return (min(values), OperatorReason.READY) if values is not None else (_NAN, reason)


class TsMax(_Rolling):
    """Rolling maximum; pointwise maximum is :class:`Maximum`."""

    def _evaluate(self):
        values, reason = self._window()
        return (max(values), OperatorReason.READY) if values is not None else (_NAN, reason)


class TsArgMin(_Rolling):
    """Oldest-to-newest argmin positions are 1..period; ties choose earliest."""

    def _evaluate(self):
        values, reason = self._window()
        if values is None:
            return _NAN, reason
        minimum = min(values)
        return float(values.index(minimum) + 1), OperatorReason.READY


class TsArgMax(_Rolling):
    """Oldest-to-newest argmax positions are 1..period; ties choose earliest."""

    def _evaluate(self):
        values, reason = self._window()
        if values is None:
            return _NAN, reason
        maximum = max(values)
        return float(values.index(maximum) + 1), OperatorReason.READY


class TsRank(_Rolling):
    """Average rank of the current value divided by the full window length."""

    def _evaluate(self):
        values, reason = self._window()
        if values is None:
            return _NAN, reason
        return _average_rank(values)[-1], OperatorReason.READY


class DecayLinear(_Rolling):
    """Linear decay with oldest weight 1 and newest weight ``period``."""

    def _evaluate(self):
        values, reason = self._window()
        if values is None:
            return _NAN, reason
        denominator = self._period * (self._period + 1) / 2.0

        def calculate() -> float:
            scale = max(abs(value) for value in values)
            if scale == 0.0:
                return 0.0
            normalized = math.fsum(
                (value / scale) * ((index + 1) / denominator) for index, value in enumerate(values)
            )
            return scale * normalized

        return _guarded_result(calculate)


def _pair_window_result(left_result, right_result):
    left, left_reason = left_result
    right, right_reason = right_result
    if left is not None and right is not None:
        return left, right, OperatorReason.READY
    if OperatorReason.NOT_READY in (left_reason, right_reason):
        return None, None, OperatorReason.NOT_READY
    return None, None, OperatorReason.INCOMPLETE_WINDOW


class _RollingPair(_Rolling):
    _mindatas = 2
    _operator_input_count = 2

    def _pair_windows(self):
        return _pair_window_result(
            self._window(self._operand(0)),
            self._window(self._operand(1)),
        )


_PANEL_ONCE_MISS = object()
_PANEL_ONCE_NO_SCALAR = object()
_MULTIPLY_APPLY = Multiply._apply


class _PanelOncePlan:
    """Per-once-call references for one exact, preloaded panel graph."""

    __slots__ = (
        "targets",
        "clock_lines",
        "feed_lines",
        "feed_lengths",
        "values",
        "members",
        "right_values",
        "outputs",
        "partitions",
    )

    def __init__(
        self,
        targets,
        clock_lines,
        feed_lines,
        feed_lengths,
        values,
        members,
        right_values,
        outputs,
        partitions,
    ):
        self.targets = targets
        self.clock_lines = clock_lines
        self.feed_lines = feed_lines
        self.feed_lengths = feed_lengths
        self.values = values
        self.members = members
        self.right_values = right_values
        self.outputs = outputs
        self.partitions = partitions


def _panel_once_readers_standard() -> bool:
    """Only bypass line access while its normal reader hooks are installed."""
    return (
        _standard_presence_relation_classes()
        and LineBuffer.__getitem__ is _LINEBUFFER_GETITEM
        and LineBuffer.__setitem__ is _LINEBUFFER_SETITEM
        and LineBuffer.__len__ is _LINEBUFFER_LEN
    )


def _panel_once_line_bindings_empty(line: Any) -> bool:
    """Require the exact standard line with no write observers attached."""
    if type(line) is not LineBuffer:
        return False
    state = _relation_instance_dict(line)
    bindings = state.get("bindings") if state is not None else None
    return type(bindings) is list and not bindings


def _panel_once_feed_shape(data: Any, end: int):
    """Return standard aligned-feed lines, or miss for a custom feed shape."""
    if type(data) is not PandasData:
        return _PANEL_ONCE_MISS
    state = _relation_instance_dict(data)
    if state is None:
        return _PANEL_ONCE_MISS
    # once_via_next dynamically calls data.advance() on every bar, which in
    # turn dispatches to the tick hooks. The panel kernel synchronizes only
    # range boundaries, so preserve replacements by taking the ordinary path.
    if (
        any(name in state for name in ("advance", "_tick_nullify", "_tick_fill"))
        or getattr(PandasData, "advance", None) is not _PANDASDATA_ADVANCE
        or getattr(PandasData, "_tick_nullify", None) is not _PANDASDATA_TICK_NULLIFY
        or getattr(PandasData, "_tick_fill", None) is not _PANDASDATA_TICK_FILL
    ):
        return _PANEL_ONCE_MISS
    if getattr(PandasData, "buflen", None) is not _PANDASDATA_BUFLEN:
        return _PANEL_ONCE_MISS
    alignment = state.get("_factor_research_alignment_v2")
    hint = state.get("_factor_research_datetime_hint")
    if type(alignment) is not dict or alignment.get("version") != 2:
        return _PANEL_ONCE_MISS
    if type(hint) is not tuple or len(hint) != 3 or type(hint[1]) is not tuple:
        return _PANEL_ONCE_MISS
    try:
        # ``ParameterAccessor`` deliberately resolves parameter names through
        # dynamic attribute lookup, so read the already-bound feed source from
        # the ordinary PandasData instance state instead of probing ``p``.
        frame = state.get("_dataname")
        frame_index = object.__getattribute__(frame, "index")
        if hint[0] is not frame_index or len(hint[1]) < end:
            return _PANEL_ONCE_MISS
    except (AttributeError, TypeError):
        return _PANEL_ONCE_MISS
    filters = state.get("_filters")
    if type(filters) is not list or filters:
        return _PANEL_ONCE_MISS

    lines = object.__getattribute__(data, "lines")
    if not _standard_lines_instance(lines):
        return _PANEL_ONCE_MISS
    cached_buflen = state.get("buflen", _PANEL_ONCE_MISS)
    if cached_buflen is not _PANEL_ONCE_MISS and (
        getattr(cached_buflen, "__self__", None) is not lines
        or getattr(cached_buflen, "__func__", None) is not _LINES_BUFLEN
    ):
        return _PANEL_ONCE_MISS
    lines_state = _relation_instance_dict(lines)
    if (
        lines_state is None
        or "buflen" in lines_state
        or getattr(type(lines), "buflen", None) is not _LINES_BUFLEN
    ):
        return _PANEL_ONCE_MISS
    line_refs = tuple(lines)
    feed_length = data.buflen()
    if end > feed_length:
        return _PANEL_ONCE_MISS
    for line in line_refs:
        if (
            type(line) is not LineBuffer
            or not _panel_once_line_bindings_empty(line)
            or line.mode != _LINEBUFFER_UNBOUNDED
            or line.extension != 0
            or type(line.array) is not _array_module.array
            or line.array.typecode != "d"
            or len(line.array) != feed_length
        ):
            return _PANEL_ONCE_MISS
    return _target_clock_line(data), line_refs, feed_length


def _panel_once_input(
    source: Any, target: Any, end: int, relation_plan=None, *, allow_scalar: bool = False
):
    """Bind one safe array reader; every other shape keeps the scalar path."""
    if type(source) in (int, float):
        if not allow_scalar:
            return _PANEL_ONCE_MISS
        value = float(source)
        if math.isinf(value):
            return _PANEL_ONCE_MISS
        return (_PANEL_ONCE_NO_SCALAR, None, value)
    if type(source) is not LineBuffer:
        return _PANEL_ONCE_MISS

    state = _relation_instance_dict(source)
    if state is None:
        return _PANEL_ONCE_MISS
    source_array = state.get("array")
    if (
        type(source_array) is not _array_module.array
        or source_array.typecode != "d"
        or len(source_array) < end
    ):
        return _PANEL_ONCE_MISS
    if _resolve_panel_relation(source, target, relation_plan) is not True:
        return _PANEL_ONCE_MISS

    reason_array = None
    marker = state.get("_factor_research_target")
    reason_line = state.get("_factor_research_reason_line")
    if marker is not None:
        if marker is not target or type(reason_line) is not LineBuffer:
            return _PANEL_ONCE_MISS
        owner = state.get("_owner")
        owner_state = _relation_instance_dict(owner)
        if owner_state is None:
            return _PANEL_ONCE_MISS
        producer = owner_state.get("_owner_ref")
        producer_type = type(producer)
        if (
            not isinstance(producer, FactorIndicator)
            or producer_type.__bases__
            not in ((CrossSectionalRank,), (_RollingCorrelationPanel,), (_MultiplyPanel,))
            or producer_type.__dict__.get("_factor_bound") is not True
            or getattr(producer, "factor_mode", None) != "native"
            or type(getattr(producer, "lines", None)) is not type(owner)
        ):
            return _PANEL_ONCE_MISS
        try:
            producer_output = producer.outputs[target]
        except (KeyError, TypeError):
            return _PANEL_ONCE_MISS
        if producer_output.value is not source or producer_output.reason is not reason_line:
            return _PANEL_ONCE_MISS
        reason_state = _relation_instance_dict(reason_line)
        if (
            reason_state is None
            or reason_state.get("_owner") is not owner
            or reason_state.get("_factor_research_target") is not target
        ):
            return _PANEL_ONCE_MISS
        reason_array = reason_state.get("array")
        if (
            type(reason_array) is not _array_module.array
            or reason_array.typecode != "d"
            or len(reason_array) < end
        ):
            return _PANEL_ONCE_MISS
    elif reason_line is not None:
        return _PANEL_ONCE_MISS

    return source_array, reason_array, _PANEL_ONCE_NO_SCALAR


def _panel_once_plan(instance: Any, optimized_class: type, start: int, end: int):
    """Capture one validated graph snapshot before entering its once kernel."""
    instance_type = type(instance)
    if (
        not _panel_once_readers_standard()
        or start < 0
        or end < start
        or instance_type.__bases__ != (optimized_class,)
        or instance_type.__dict__.get("_factor_bound") is not True
        or getattr(instance, "factor_mode", None) != "native"
    ):
        return None
    if optimized_class is _MultiplyPanel and Multiply._apply is not _MULTIPLY_APPLY:
        return None

    targets = tuple(instance._factor_target_datas)
    datas = tuple(instance.datas)
    if not targets or len(datas) != len(targets) or any(
        data is not target for data, target in zip(datas, targets)
    ):
        return None

    clock_lines = []
    feed_lines = []
    feed_lengths = []
    for target in targets:
        feed_shape = _panel_once_feed_shape(target, end)
        if feed_shape is _PANEL_ONCE_MISS:
            return None
        clock, lines, length = feed_shape
        clock_lines.append(clock)
        feed_lines.append(lines)
        feed_lengths.append(length)

    values = []
    members = []
    right_values = []
    outputs = []
    member_plans = getattr(instance, "_member_relation_plans", ())
    for index, target in enumerate(targets):
        relation_plan = member_plans[index] if index < len(member_plans) else None
        value = _panel_once_input(instance._values[index], target, end)
        if value is _PANEL_ONCE_MISS:
            return None
        values.append(value)

        member = instance._members[index]
        if member is None:
            members.append(None)
        else:
            member_value = _panel_once_input(member, target, end, relation_plan)
            if member_value is _PANEL_ONCE_MISS:
                return None
            members.append(member_value)

        if isinstance(instance, _PairedPanelOperator):
            right = _panel_once_input(
                instance._right_values[index], target, end, allow_scalar=True
            )
            if right is _PANEL_ONCE_MISS:
                return None
            right_values.append(right)

        target_outputs = instance.outputs[target]
        output_value = target_outputs.value
        output_reason = target_outputs.reason
        if any(
            type(line) is not LineBuffer
            or not _panel_once_line_bindings_empty(line)
            or type(line.array) is not _array_module.array
            or line.array.typecode != "d"
            or len(line.array) < end
            for line in (output_value, output_reason)
        ):
            return None
        outputs.append((output_value, output_reason))

    partitions = None
    if isinstance(instance, CrossSectionalRank):
        try:
            group_keys = instance._static_group_keys()
        except Exception:
            return None
        if any(
            group is not None
            and type(group) not in (str, int, float, bool)
            for group in group_keys
        ):
            return None
        grouped = {}
        for index, group in enumerate(group_keys):
            if isinstance(group, float) and not math.isfinite(group):
                return None
            grouped.setdefault((type(group), group), []).append(index)
        partitions = tuple(tuple(indices) for indices in grouped.values())

    return _PanelOncePlan(
        tuple(targets),
        tuple(clock_lines),
        tuple(feed_lines),
        tuple(feed_lengths),
        tuple(values),
        tuple(members),
        tuple(right_values),
        tuple(outputs),
        partitions,
    )


def _panel_once_advance_feeds(plan: _PanelOncePlan, index: int) -> None:
    """Match an aligned feed's standard cursor/tick state without child walks."""
    logical_length = index + 1
    for target, lines, feed_length in zip(plan.targets, plan.feed_lines, plan.feed_lengths):
        target._tick_nullify()
        for line in lines:
            line._idx = index
            line.lencount = logical_length
        if logical_length < feed_length:
            target._tick_fill()


def _panel_once_reason(reason_array: Any, index: int):
    """Classify a marked producer reason only when its value is NaN."""
    if reason_array is None or index < 0 or index >= len(reason_array):
        return None
    try:
        raw_reason = float(reason_array[index])
        if not math.isfinite(raw_reason) or raw_reason != int(raw_reason):
            return None
        reason = OperatorReason(int(raw_reason))
    except (IndexError, TypeError, ValueError, OverflowError):
        return None
    return reason if reason is not OperatorReason.READY else None


def _panel_once_read(source, index: int):
    source_array, reason_array, scalar = source
    if scalar is not _PANEL_ONCE_NO_SCALAR:
        value = float(scalar)
        if math.isinf(value):
            raise OperatorInputError("scalar operator input contains infinity")
        if math.isnan(value):
            return _NAN, OperatorReason.NONFINITE_INPUT
        return value, OperatorReason.READY
    if index < 0 or index >= len(source_array):
        return _NAN, OperatorReason.NOT_READY
    value = float(source_array[index])
    if math.isinf(value):
        raise OperatorInputError("panel input line contains infinity")
    if math.isnan(value):
        return _NAN, _panel_once_reason(reason_array, index) or OperatorReason.NONFINITE_INPUT
    return value, OperatorReason.READY


def _panel_once_window(source, index: int, period: int):
    source_array, reason_array, scalar = source
    start = index - period + 1
    if start < 0:
        return None, OperatorReason.NOT_READY
    values = []
    if scalar is not _PANEL_ONCE_NO_SCALAR:
        value = float(scalar)
        if math.isinf(value):
            raise OperatorInputError("scalar operator input contains infinity")
        if math.isnan(value):
            return None, OperatorReason.INCOMPLETE_WINDOW
        return [value] * period, OperatorReason.READY
    for absolute_index in range(start, index + 1):
        if absolute_index >= len(source_array):
            return None, OperatorReason.NOT_READY
        value = float(source_array[absolute_index])
        if math.isinf(value):
            raise OperatorInputError("panel input line contains infinity")
        if math.isnan(value):
            _panel_once_reason(reason_array, absolute_index)
            return None, OperatorReason.INCOMPLETE_WINDOW
        values.append(value)
    return values, OperatorReason.READY


_FLOAT64_EPSILON = 2.220446049250313e-16


def _centered_unit_deviations(
    values: Sequence[float],
) -> Optional[Tuple[List[float], List[float]]]:
    """Return centered deviations scaled to unit magnitude and their scale factors.

    Subtracting an anchor before taking a mean preserves ULP-sized movement on
    top of a large offset.  If an opposite-sign pair makes that subtraction
    overflow, values are first divided by their largest input magnitude.  The
    returned factors keep the physical deviation scale available to covariance
    without multiplying it prematurely.
    """
    anchor = values[0]
    differences = [value - anchor for value in values]
    scale_factors = []
    if not all(math.isfinite(value) for value in differences):
        input_scale = max(abs(value) for value in values)
        if input_scale == 0.0:
            return None
        scaled_anchor = anchor / input_scale
        differences = [value / input_scale - scaled_anchor for value in values]
        scale_factors.append(input_scale)

    difference_scale = max(abs(value) for value in differences)
    if difference_scale == 0.0:
        return None
    normalized = [value / difference_scale for value in differences]
    mean = math.fsum(normalized) / len(normalized)
    centered = [value - mean for value in normalized]
    centered_scale = max(abs(value) for value in centered)
    if centered_scale == 0.0:
        return None

    unit = [value / centered_scale for value in centered]
    scale_factors.extend((difference_scale, centered_scale))
    return unit, scale_factors


class RollingCovariance(_RollingPair):
    """Population covariance (ddof=0); a one-value window is zero.

    Stable float64 kernel: anchor-center each series, independently scale its
    centered deviations, and accumulate with ``math.fsum``.  The scale factors
    are combined with exponent-safe multiplication only after the normalized
    covariance is known.  A constant window has covariance exactly 0 (it is
    not a domain error); a one-value population covariance is 0 as well.
    """

    def _evaluate(self):
        left, right, reason = self._pair_windows()
        if left is None:
            return _NAN, reason

        def calculate() -> float:
            count = len(left)
            if count == 1:
                return 0.0
            if all(value == left[0] for value in left) or all(value == right[0] for value in right):
                return 0.0
            centered_left = _centered_unit_deviations(left)
            centered_right = _centered_unit_deviations(right)
            if centered_left is None or centered_right is None:
                return 0.0
            normalized_left, left_scales = centered_left
            normalized_right, right_scales = centered_right
            covariance = math.fsum(a * b for a, b in zip(normalized_left, normalized_right))
            return _stable_product([covariance, 1.0 / count] + left_scales + right_scales)

        return _guarded_result(calculate)


def _correlation_window_result(
    left: Sequence[float], right: Sequence[float]
) -> Tuple[float, OperatorReason]:
    """Apply the scalar rolling-correlation float64 kernel to two full windows."""

    def calculate() -> float:
        if all(value == left[0] for value in left) or all(value == right[0] for value in right):
            raise ValueError("correlation requires non-constant inputs")
        centered_left = _centered_unit_deviations(left)
        centered_right = _centered_unit_deviations(right)
        if centered_left is None or centered_right is None:
            raise ValueError("correlation requires non-constant inputs")
        deviations_left, _ = centered_left
        deviations_right, _ = centered_right
        left_ss = math.fsum(value * value for value in deviations_left)
        right_ss = math.fsum(value * value for value in deviations_right)
        cross = math.fsum(a * b for a, b in zip(deviations_left, deviations_right))
        correlation = cross / (math.sqrt(left_ss) * math.sqrt(right_ss))
        if not math.isfinite(correlation):
            raise ValueError("correlation result is outside its mathematical domain")
        if correlation > 1.0:
            if correlation <= 1.0 + 4.0 * _FLOAT64_EPSILON:
                return 1.0
            raise ValueError("correlation result is outside its mathematical domain")
        if correlation < -1.0:
            if correlation >= -1.0 - 4.0 * _FLOAT64_EPSILON:
                return -1.0
            raise ValueError("correlation result is outside its mathematical domain")
        return correlation

    try:
        return calculate(), OperatorReason.READY
    except (ArithmeticError, ValueError):
        return _NAN, OperatorReason.DOMAIN_ERROR


class RollingCorrelation(_RollingPair):
    """Pearson correlation on two complete windows; constant input is invalid."""

    def _evaluate(self):
        if self._period < 2:
            return _NAN, OperatorReason.DOMAIN_ERROR
        left, right, reason = self._pair_windows()
        if left is None:
            return _NAN, reason
        return _correlation_window_result(left, right)


class _PanelOperator(FactorIndicator):
    """FactorIndicator-backed node with one scalar output for each bound feed."""

    lines: Any = ("value", "reason")
    params: Any = (
        ("line_inputs", None),
        ("field", None),
        ("members", None),
        ("groups", None),
        ("level", None),
        ("a", 1.0),
    )

    def __init__(self) -> None:
        super().__init__()
        targets = tuple(self._factor_target_datas)
        if self.p.line_inputs is None:
            if not isinstance(self.p.field, str) or not self.p.field:
                raise ValueError("panel operator requires values= or field=")
            self._values = tuple(getattr(data, self.p.field) for data in targets)
        else:
            self._values = tuple(self.p.line_inputs)
        if len(self._values) != len(targets):
            raise ValueError("values must contain one line operand per bound feed")

        if self.p.members is None:
            self._members = (None,) * len(targets)
        else:
            self._members = tuple(self.p.members)
            if len(self._members) != len(targets):
                raise ValueError("members must contain one line operand per bound feed")

        self._groups = None
        if self.p.groups is not None:
            self._groups = tuple(self.p.groups)
            if len(self._groups) != len(targets):
                raise ValueError("groups must contain one feed category line per bound feed")

        # Keep a live-guarded relation proof for the repeated standard
        # formula-presence reads; all other inputs use the general resolver.
        self._member_relation_plans = tuple(
            _presence_line_relation_plan(member, target) if member is not None else None
            for target, member in zip(targets, self._members)
        )

        # A FactorIndicator has one native owner clock for all output lines.
        # Retain the target identity on each line so downstream operators can
        # validate a later target without replacing or manually advancing deps.
        for data in targets:
            output_lines = self.outputs[data]._lines
            output_lines["value"]._factor_research_target = data
            output_lines["value"]._factor_research_reason_line = output_lines["reason"]
            for output_line in output_lines.values():
                output_line._factor_research_target = data

    @classmethod
    def bind(cls, *datas: Any, **params: Any) -> Any:
        """Bind this panel node as a native FactorIndicator child."""
        if not datas:
            raise ValueError("panel operators require at least one feed")
        if "values" in params:
            if "line_inputs" in params:
                raise ValueError("pass only one of values= or line_inputs=")
            params["line_inputs"] = params.pop("values")
        if cls is IndNeutralize and params.get("level") not in _LEVELS:
            raise ValueError("level must be sector, industry, or subindustry")
        if cls is CrossSectionalScale:
            scale = params.get("a", 1.0)
            if isinstance(scale, bool) or not isinstance(scale, numbers.Real):
                raise ValueError("scale a must be a finite positive real number")
            if not math.isfinite(float(scale)) or float(scale) <= 0.0:
                raise ValueError("scale a must be a finite positive real number")
        return super().bind(*datas, **params)

    def _active_values(self) -> Tuple[List[float], List[bool], List[OperatorReason]]:
        values: List[float] = []
        eligible: List[bool] = []
        reasons: List[OperatorReason] = []
        for index, (target, source, member) in enumerate(
            zip(self._factor_target_datas, self._values, self._members)
        ):
            if member is None:
                is_member = True
            else:
                member_value, member_reason = _read_panel_value(
                    member, target, self._member_relation_plans[index]
                )
                if member_reason is not OperatorReason.READY:
                    raise OperatorInputError("formula-universe membership is unknown")
                if member_value not in (0.0, 1.0):
                    raise OperatorInputError("panel membership must be 0/1/unknown")
                is_member = member_value == 1.0
            if not is_member:
                values.append(_NAN)
                eligible.append(False)
                reasons.append(OperatorReason.FORMULA_INELIGIBLE)
                continue
            value, reason = _read_panel_value(source, target)
            values.append(value)
            eligible.append(reason is OperatorReason.READY)
            reasons.append(reason)
        return values, eligible, reasons

    def _write_panel(self, values: Sequence[float], reasons: Sequence[OperatorReason]) -> None:
        for data, value, reason in zip(self._factor_target_datas, values, reasons):
            self.outputs[data].value[0] = value
            self.outputs[data].reason[0] = float(reason)

    def _static_group_keys(self) -> List[Any]:
        """Return validated per-feed static research-group keys."""
        if self._groups is None:
            return [None] * len(self._factor_target_datas)
        keys: List[Any] = []
        for group in self._groups:
            if group is None or _is_line_operand(group):
                raise OperatorInputError("cross-sectional groups must be known static labels")
            if isinstance(group, numbers.Real) and not math.isfinite(float(group)):
                raise OperatorInputError("cross-sectional groups must be known static labels")
            try:
                hash(group)
            except TypeError as exc:
                raise OperatorInputError("cross-sectional group labels must be hashable") from exc
            keys.append(group)
        return keys

    def _evaluate_panel(self) -> None:
        raise NotImplementedError

    def next(self) -> None:
        self._evaluate_panel()


class _LogicalOperatorView:
    """Non-scheduled, one-target view of a physical paired panel operator."""

    def __init__(
        self,
        physical_panel: Any,
        asset_index: int,
        target: Any,
        operands: Sequence[Any],
    ) -> None:
        self._physical_panel = physical_panel
        self._asset_index = int(asset_index)
        self._target_data = target
        self._logical_operator_type = physical_panel._logical_operator_type
        self._operand_args = tuple(operands)
        self.lines = physical_panel.outputs[target]
        self.p = physical_panel.p
        self._period = getattr(physical_panel, "_period", None)
        self.datas = tuple(value for value in self._operand_args if _is_line_operand(value))
        for index, operand in enumerate(self._operand_args):
            setattr(self, "data%d" % index, operand)


class _PairedPanelOperator(_PanelOperator):
    """One ordinary panel Indicator that evaluates independent per-target pairs."""

    params: Any = (("right_inputs", None),)
    _logical_operator_type: Any = None

    def __init__(self) -> None:
        super().__init__()
        if self.p.right_inputs is None:
            raise ValueError("paired panel operator requires right_values=")
        self._right_values = tuple(self.p.right_inputs)
        if len(self._right_values) != len(self._factor_target_datas):
            raise ValueError("right_values must contain one operand per bound feed")
        input_minperiod = 1
        for operand in self._values + self._right_values:
            if isinstance(operand, bool) or not (
                _is_line_operand(operand) or isinstance(operand, numbers.Real)
            ):
                raise OperatorInputError("operator inputs must be lines or real scalar constants")
            if isinstance(operand, numbers.Real):
                if math.isinf(float(operand)):
                    raise OperatorInputError("scalar operator input contains infinity")
                continue
            source_owner = getattr(operand, "_owner", None)
            source_owner = getattr(source_owner, "_owner_ref", None) or source_owner
            input_minperiod = max(
                input_minperiod,
                int(getattr(operand, "_minperiod", 1)),
                int(getattr(source_owner, "_minperiod", 1)),
            )
        if input_minperiod > 1:
            # Panel binding uses the target feeds as its clock inputs. Preserve
            # a pair operand's ordinary indicator minperiod explicitly, as a
            # scalar operator would inherit it through its line dependencies.
            self.addminperiod(input_minperiod)

    @classmethod
    def bind(cls, *datas: Any, **params: Any) -> Any:
        if "right_values" in params:
            if "right_inputs" in params:
                raise ValueError("pass only one of right_values= or right_inputs=")
            params["right_inputs"] = params.pop("right_values")
        return super().bind(*datas, **params)

    def _evaluate_target(self, asset_index: int) -> Tuple[float, OperatorReason]:
        raise NotImplementedError

    def _evaluate_panel(self) -> None:
        values: List[float] = []
        reasons: List[OperatorReason] = []
        context = self._factor_strict_context_for_callback()
        phase = getattr(context, "phase", "next") if context is not None else "next"
        for asset_index, target in enumerate(self._factor_target_datas):
            try:
                value, reason = self._evaluate_target(asset_index)
            except Exception as exc:
                if context is None:
                    raise
                # The panel itself spans every feed. Attribute failures through
                # the concrete target, which the parent strict context binds.
                from .strict import fail_computation

                fail_computation(context, exc, phase, operation=target)
            values.append(value)
            reasons.append(reason)
        self._write_panel(values, reasons)


class _RollingCorrelationPanel(_PairedPanelOperator):
    """Physical rolling-correlation panel with scalar logical target views."""

    params: Any = (("period", 1),)
    _logical_operator_type = RollingCorrelation

    def __init__(self) -> None:
        period = _floor_window(self.p.period, "period")
        super().__init__()
        self._period = period
        self.addminperiod(self._period)

    def qbuffer(self, savemem=0):
        """Retain each input window even though logical views are unscheduled.

        Paired panels read their input lines directly, so Backtrader cannot
        infer the rolling dependency from the normal indicator graph. Record
        this consumer's storage requirement before the source indicators
        configure their qbuffers, and grow an already configured source when
        traversal reaches this consumer later.
        """
        if savemem:
            for source in self._values + self._right_values:
                if not isinstance(source, LineBuffer):
                    continue
                source.updateminperiod(self._period)
                source.minbuffer(self._period)
        super().qbuffer(savemem=savemem)

    def next(self) -> None:
        self._evaluate_panel()

    def once(self, start: int, end: int) -> None:
        _panel_once_callback(self, _RollingCorrelationPanel, start, end)

    def _evaluate_target(self, asset_index: int) -> Tuple[float, OperatorReason]:
        if self._period < 2:
            return _NAN, OperatorReason.DOMAIN_ERROR
        target = self._factor_target_datas[asset_index]
        left, right, reason = _pair_window_result(
            _read_panel_window(self._values[asset_index], target, self._period),
            _read_panel_window(self._right_values[asset_index], target, self._period),
        )
        if left is None:
            return _NAN, reason
        return _correlation_window_result(left, right)


class _MultiplyPanel(_PairedPanelOperator):
    """Physical pointwise-multiply panel with scalar logical target views."""

    _logical_operator_type = Multiply

    def next(self) -> None:
        self._evaluate_panel()

    def once(self, start: int, end: int) -> None:
        _panel_once_callback(self, _MultiplyPanel, start, end)

    def _evaluate_target(self, asset_index: int) -> Tuple[float, OperatorReason]:
        target = self._factor_target_datas[asset_index]
        left, right, reason = _line_pair_results(
            _read_panel_operand(self._values[asset_index], target),
            _read_panel_operand(self._right_values[asset_index], target),
        )
        if reason is not OperatorReason.READY:
            return _NAN, reason
        try:
            return _result(Multiply._apply(left, right))
        except (ValueError, ZeroDivisionError, OverflowError):
            return _NAN, OperatorReason.DOMAIN_ERROR


class CrossSectionalRank(_PanelOperator):
    """Average-tie cross-sectional rank divided by finite member count."""

    lines: Any = ("value", "reason")

    def next(self) -> None:
        self._evaluate_panel()

    def once(self, start: int, end: int) -> None:
        _panel_once_callback(self, CrossSectionalRank, start, end)

    def _evaluate_panel(self) -> None:
        values, eligible, reasons = self._active_values()
        group_keys = self._static_group_keys()
        partitions: Dict[Tuple[type, Any], List[int]] = {}
        for index, group in enumerate(group_keys):
            partitions.setdefault((type(group), group), []).append(index)
        results = [_NAN] * len(values)
        for indices in partitions.values():
            valid_indices = [index for index in indices if eligible[index]]
            ranks = _average_rank([values[index] for index in valid_indices])
            for rank_index, asset_index in enumerate(valid_indices):
                results[asset_index] = ranks[rank_index]
                reasons[asset_index] = OperatorReason.READY
        self._write_panel(results, reasons)


def _panel_once_callback(
    instance: Any, optimized_class: type, start: int, end: int
) -> None:
    """Use an ordinary Indicator once hook only for a proven panel snapshot."""
    try:
        plan = _panel_once_plan(instance, optimized_class, start, end)
    except Exception:
        # Eligibility is an optimization probe; unusual user objects keep the
        # established ordinary callback path, including its original failures.
        plan = None
    if plan is None:
        Indicator.once_via_next(instance, start, end)
        return

    def calculate(first: int, last: int) -> None:
        _run_panel_once(instance, optimized_class, plan, first, last)

    if not _factor_once_execute(instance, optimized_class, calculate, start, end):
        Indicator.once_via_next(instance, start, end)


def _run_panel_once(
    instance: Any, optimized_class: type, plan: _PanelOncePlan, start: int, end: int
) -> None:
    if optimized_class is CrossSectionalRank:
        _run_rank_panel_once(instance, plan, start, end)
    else:
        _run_paired_panel_once(instance, optimized_class, plan, start, end)


def _write_panel_once_outputs(
    plan: _PanelOncePlan,
    index: int,
    values: Sequence[float],
    reasons: Sequence[OperatorReason],
) -> None:
    for output, value, reason in zip(plan.outputs, values, reasons):
        _factor_once_write(output[0], index, value)
        _factor_once_write(output[1], index, float(reason))


def _run_rank_panel_once(
    instance: CrossSectionalRank, plan: _PanelOncePlan, start: int, end: int
) -> None:
    for index in range(start, end):
        try:
            values: List[float] = []
            eligible: List[bool] = []
            reasons: List[OperatorReason] = []
            for asset_index, member in enumerate(plan.members):
                if member is None:
                    is_member = True
                else:
                    member_value, member_reason = _panel_once_read(member, index)
                    if member_reason is not OperatorReason.READY:
                        raise OperatorInputError("formula-universe membership is unknown")
                    if member_value not in (0.0, 1.0):
                        raise OperatorInputError("panel membership must be 0/1/unknown")
                    is_member = member_value == 1.0
                if not is_member:
                    values.append(_NAN)
                    eligible.append(False)
                    reasons.append(OperatorReason.FORMULA_INELIGIBLE)
                    continue
                value, reason = _panel_once_read(plan.values[asset_index], index)
                values.append(value)
                eligible.append(reason is OperatorReason.READY)
                reasons.append(reason)

            results = [_NAN] * len(values)
            for indices in plan.partitions:
                valid_indices = [asset_index for asset_index in indices if eligible[asset_index]]
                ranks = _average_rank([values[asset_index] for asset_index in valid_indices])
                for rank_index, asset_index in enumerate(valid_indices):
                    results[asset_index] = ranks[rank_index]
                    reasons[asset_index] = OperatorReason.READY
            _write_panel_once_outputs(plan, index, results, reasons)
        except BaseException:
            try:
                _panel_once_advance_feeds(plan, index)
            except Exception:
                # The exact standard feed and line hooks were validated before
                # this callback. Preserve the original calculation failure if
                # an unexpected synchronization error nevertheless occurs.
                pass
            raise

    if start < end:
        _panel_once_advance_feeds(plan, end - 1)


def _run_paired_panel_once(
    instance: _PairedPanelOperator,
    optimized_class: type,
    plan: _PanelOncePlan,
    start: int,
    end: int,
) -> None:
    context = instance._factor_strict_context_for_callback()
    phase = getattr(context, "phase", "once_via_next") if context is not None else "once_via_next"
    for index in range(start, end):
        feeds_synced = False
        try:
            values: List[float] = []
            reasons: List[OperatorReason] = []
            for asset_index, target in enumerate(plan.targets):
                try:
                    if optimized_class is _RollingCorrelationPanel:
                        if instance._period < 2:
                            value, reason = _NAN, OperatorReason.DOMAIN_ERROR
                        else:
                            left, right, pair_reason = _pair_window_result(
                                _panel_once_window(
                                    plan.values[asset_index], index, instance._period
                                ),
                                _panel_once_window(
                                    plan.right_values[asset_index], index, instance._period
                                ),
                            )
                            if left is None:
                                value, reason = _NAN, pair_reason
                            else:
                                value, reason = _correlation_window_result(left, right)
                    else:
                        left, right, pair_reason = _line_pair_results(
                            _panel_once_read(plan.values[asset_index], index),
                            _panel_once_read(plan.right_values[asset_index], index),
                        )
                        if pair_reason is not OperatorReason.READY:
                            value, reason = _NAN, pair_reason
                        else:
                            try:
                                value, reason = _result(_MULTIPLY_APPLY(left, right))
                            except (ValueError, ZeroDivisionError, OverflowError):
                                value, reason = _NAN, OperatorReason.DOMAIN_ERROR
                except Exception as exc:
                    if context is None:
                        raise
                    from .strict import fail_computation

                    try:
                        _panel_once_advance_feeds(plan, index)
                    except Exception:
                        # Keep the original strict-computation cause if the
                        # validated standard feed synchronization fails.
                        pass
                    feeds_synced = True
                    fail_computation(context, exc, phase, operation=target)
                values.append(value)
                reasons.append(reason)
            _write_panel_once_outputs(plan, index, values, reasons)
        except BaseException:
            if not feeds_synced:
                try:
                    _panel_once_advance_feeds(plan, index)
                except Exception:
                    # Keep the original calculation/wrapping exception chain.
                    pass
            raise

    if start < end:
        _panel_once_advance_feeds(plan, end - 1)


CrossSectionalRank._factor_once_expected_callbacks = (
    ("next", CrossSectionalRank.__dict__["next"]),
    ("once", CrossSectionalRank.__dict__["once"]),
)
_RollingCorrelationPanel._factor_once_expected_callbacks = (
    ("next", _RollingCorrelationPanel.__dict__["next"]),
    ("once", _RollingCorrelationPanel.__dict__["once"]),
)
_MultiplyPanel._factor_once_expected_callbacks = (
    ("next", _MultiplyPanel.__dict__["next"]),
    ("once", _MultiplyPanel.__dict__["once"]),
)


class CrossSectionalScale(_PanelOperator):
    """Scale finite formula members by ``a*x / sum(abs(x))``."""

    lines: Any = ("value", "reason")

    def _evaluate_panel(self) -> None:
        values, eligible, reasons = self._active_values()
        group_keys = self._static_group_keys()
        scale = self.p.a
        if isinstance(scale, bool) or not isinstance(scale, numbers.Real):
            raise ValueError("scale a must be a finite positive real number")
        scale = float(scale)
        if not math.isfinite(scale) or scale <= 0.0:
            raise ValueError("scale a must be a finite positive real number")
        results = [_NAN] * len(values)
        partitions: Dict[Tuple[type, Any], List[int]] = {}
        for index, group in enumerate(group_keys):
            partitions.setdefault((type(group), group), []).append(index)
        for indices in partitions.values():
            valid_indices = [index for index in indices if eligible[index]]
            if not valid_indices:
                continue
            magnitude = max(abs(values[index]) for index in valid_indices)
            if magnitude == 0.0:
                for index in valid_indices:
                    reasons[index] = OperatorReason.DOMAIN_ERROR
                continue
            denominator = math.fsum(abs(values[index] / magnitude) for index in valid_indices)
            for index in valid_indices:
                results[index], reasons[index] = _guarded_result(
                    lambda index=index, magnitude=magnitude, denominator=denominator: (
                        scale * (values[index] / magnitude) / denominator
                    )
                )
        self._write_panel(results, reasons)


class IndNeutralize(_PanelOperator):
    """Subtract a finite-value group mean using an ordinary feed category line.

    ``level`` must be one of ``sector``, ``industry`` or ``subindustry``.  If
    ``groups`` is omitted, each bound feed must expose a same-named line.
    Unknown category values are excluded from all group means and produce
    NaN/UNKNOWN_CLASSIFICATION for that asset.  A one-member group maps to 0.
    """

    lines: Any = ("value", "reason")

    def __init__(self) -> None:
        super().__init__()
        if self.p.level not in _LEVELS:
            raise ValueError("level must be sector, industry, or subindustry")
        if self._groups is None:
            try:
                self._groups = tuple(
                    getattr(data, self.p.level) for data in self._factor_target_datas
                )
            except AttributeError as exc:
                raise ValueError("all feeds require the requested feed category line") from exc

    def _evaluate_panel(self) -> None:
        values, eligible, reasons = self._active_values()
        groups = self._groups
        if groups is None:
            raise RuntimeError("industry neutralization has no category-line binding")
        categories: List[Optional[float]] = []
        for index, group_line in enumerate(groups):
            if not eligible[index]:
                categories.append(None)
                continue
            category, category_reason = _read_panel_value(
                group_line, self._factor_target_datas[index]
            )
            if category_reason is OperatorReason.READY:
                categories.append(category)
            else:
                categories.append(None)
                reasons[index] = OperatorReason.UNKNOWN_CLASSIFICATION

        members: Dict[float, List[int]] = {}
        for index, category_key in enumerate(categories):
            if eligible[index] and category_key is not None:
                members.setdefault(category_key, []).append(index)
        results = [_NAN] * len(values)
        for category, indices in members.items():
            mean = _stable_mean([values[index] for index in indices])
            for index in indices:
                results[index], reasons[index] = _result(values[index] - mean)
        self._write_panel(results, reasons)


__all__ = (
    "Add",
    "Abs",
    "CrossSectionalRank",
    "CrossSectionalScale",
    "DecayLinear",
    "Delay",
    "Delta",
    "Divide",
    "EqualTo",
    "GreaterEqual",
    "GreaterThan",
    "IndNeutralize",
    "LessEqual",
    "LessThan",
    "Log",
    "LogicalAnd",
    "LogicalNot",
    "LogicalOr",
    "Maximum",
    "Minimum",
    "Multiply",
    "Negate",
    "NotEqualTo",
    "OperatorInputError",
    "OperatorReason",
    "Power",
    "REASON_NAMES",
    "RollingCorrelation",
    "RollingCovariance",
    "RollingMean",
    "RollingProduct",
    "RollingStd",
    "RollingSum",
    "Sign",
    "SignedPower",
    "Sqrt",
    "Subtract",
    "TsArgMax",
    "TsArgMin",
    "TsMax",
    "TsMin",
    "TsRank",
    "Where",
)
