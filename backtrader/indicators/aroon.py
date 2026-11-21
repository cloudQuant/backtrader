#!/usr/bin/env python
"""Aroon Indicator Module - Aroon trend indicator.

This module provides the Aroon indicator developed by Tushar Chande in 1995
to identify trend strength and direction.

Classes:
    _AroonBase: Base class for Aroon indicators.
    AroonUp: Aroon Up component.
    AroonDown: Aroon Down component.
    AroonUpDown: Combined Aroon Up and Down (alias: AroonIndicator).
    AroonOscillator: Aroon Oscillator (alias: AroonOsc).
    AroonUpDownOscillator: Combined AroonUpDown and Oscillator (alias: AroonUpDownOsc).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.aroon = bt.indicators.AroonUpDown(self.data, period=14)

        def next(self):
            if self.aroon.aroonup[0] > self.aroon.aroondown[0]:
                self.buy()
            elif self.aroon.aroonup[0] < self.aroon.aroondown[0]:
                self.sell()
"""

import array
import inspect
import types
from collections import deque

from . import FindFirstIndexHighest, FindFirstIndexLowest, Indicator
from . import basicops as _basicops
from ..linebuffer import LineBuffer
from ..lineseries import Lines
from ..parameters import ParameterManager

_LINE_GETATTRIBUTE = inspect.getattr_static(LineBuffer, "__getattribute__")
_LINES_GETITEM = inspect.getattr_static(Lines, "__getitem__")
_PARAM_GET = inspect.getattr_static(ParameterManager, "get")
_LINES_GETITEM_CODE = _LINES_GETITEM.__code__
_PARAM_GET_CODE = _PARAM_GET.__code__
_PARAM_GET_DEFAULTS = _PARAM_GET.__defaults__
_ACCESSOR_GETATTRIBUTE = vars(_basicops.ParameterAccessor)["__getattribute__"]
_ACCESSOR_GETATTRIBUTE_CODE = _ACCESSOR_GETATTRIBUTE.__code__
_ACCESSOR_DIRECT_ATTRS = _ACCESSOR_GETATTRIBUTE.__globals__["_PARAMETER_ACCESSOR_DIRECT_ATTRS"]
_FIND_FIRST_FUNC = _basicops._FIND_FIRST_INDEX_FUNC
_FIND_FIRST_CODE = _FIND_FIRST_FUNC.__code__
_PARAM_DICT = inspect.getattr_static(ParameterManager, "__dict__")
_LINE_DICT = inspect.getattr_static(LineBuffer, "__dict__")
_LINES_DICT = inspect.getattr_static(Lines, "__dict__")


def _plain_state(value, descriptor):
    """Read a plain instance dictionary without invoking custom key equality."""
    if (
        type(type(value)) is not type
        or type(descriptor) is not types.GetSetDescriptorType
        or inspect.getattr_static(type(value), "__dict__") is not descriptor
    ):
        return None
    state = object.__getattribute__(value, "__dict__")
    if type(state) is not dict or any(type(key) is not str for key in state):
        return None
    return state


def _plain_aroon(indicator, expected):
    cls = type(indicator)
    expected_dict = _FAST_CLASS_DICTS.get(cls)
    if expected_dict is None or type(cls) is not type:
        return False
    accessor = _basicops.ParameterAccessor
    accessor_globals = _ACCESSOR_GETATTRIBUTE.__globals__
    if type(accessor_globals) is not dict or any(type(key) is not str for key in accessor_globals):
        return False
    if (
        accessor is not _basicops._INDEX_ACCESSOR_CLASS
        or vars(accessor).get("__getattribute__") is not _basicops._INDEX_ACCESSOR_GETATTRIBUTE
        or vars(accessor).get("__getattribute__") is not _ACCESSOR_GETATTRIBUTE
        or _ACCESSOR_GETATTRIBUTE.__code__ is not _ACCESSOR_GETATTRIBUTE_CODE
        or accessor_globals.get("_PARAMETER_ACCESSOR_DIRECT_ATTRS") is not _ACCESSOR_DIRECT_ATTRS
    ):
        return False
    for base in type.__getattribute__(cls, "__mro__"):
        ns = type.__getattribute__(base, "__dict__")
        if "__getattribute__" in ns:
            if ns["__getattribute__"] is not object.__getattribute__:
                return False
            break
    else:
        return False
    for check, descriptor in ((cls, expected_dict), (accessor, _basicops._INDEX_ACCESSOR_DICT)):
        for base in type.__getattribute__(check, "__mro__"):
            ns = type.__getattribute__(base, "__dict__")
            if "__dict__" in ns:
                if ns["__dict__"] is not descriptor:
                    return False
                break
        else:
            return False
    for base in type.__getattribute__(cls, "__mro__"):
        ns = type.__getattribute__(base, "__dict__")
        if "p" in ns:
            if ns["p"] is not _basicops._INDEX_INDICATOR_P:
                return False
            break
    else:
        return False
    if any(
        "_evalfunc" in type.__getattribute__(base, "__dict__")
        for base in type.__getattribute__(accessor, "__mro__")
    ):
        return False
    state = object.__getattribute__(indicator, "__dict__")
    if type(state) is not dict or any(type(key) is not str for key in state):
        return False
    params = state.get("_params_instance")
    if type(params) is not accessor:
        return False
    state = object.__getattribute__(params, "__dict__")
    return (
        type(state) is dict
        and all(type(key) is str for key in state)
        and state.get("_evalfunc") is expected
    )


def _safe_rolling_inputs(indicator, start, end):
    """Use raw state only when ordinary lookups cannot execute user code."""
    if type(start) is not int or type(end) is not int or not 0 <= start <= end:
        return None
    try:
        state = object.__getattribute__(indicator, "__dict__")
        params = state["_params_instance"]
        manager = object.__getattribute__(params, "__dict__")["_param_manager"]
        if (
            type(manager) is not ParameterManager
            or inspect.getattr_static(ParameterManager, "get") is not _PARAM_GET
            or _PARAM_GET.__code__ is not _PARAM_GET_CODE
            or _PARAM_GET.__defaults__ is not _PARAM_GET_DEFAULTS
            or inspect.getattr_static(ParameterManager, "__getattribute__")
            is not object.__getattribute__
        ):
            return None
        mstate = _plain_state(manager, _PARAM_DICT)
        if mstate is None or "get" in mstate:
            return None
        for name in ("_descriptors", "_values", "_lazy_defaults"):
            if (
                type(mstate.get(name)) is not dict
                or any(type(key) is not str for key in mstate[name])
                or any(
                    name in type.__getattribute__(base, "__dict__")
                    for base in type.__getattribute__(ParameterManager, "__mro__")
                )
            ):
                return None
        values = mstate.get("_values")
        if type(values) is not dict or "period" not in values:
            return None
        period = values["period"]
        if type(period) is not int or period <= 0:
            return None
        data = inspect.getattr_static(indicator, "data")
        lines = inspect.getattr_static(indicator, "lines")
        if (
            type(data) is not LineBuffer
            or inspect.getattr_static(LineBuffer, "__getattribute__") is not _LINE_GETATTRIBUTE
            or _LINE_GETATTRIBUTE is not object.__getattribute__
            or inspect.getattr_static(type(lines), "__getattribute__")
            is not object.__getattribute__
            or inspect.getattr_static(type(lines), "__getitem__") is not _LINES_GETITEM
            or inspect.getattr_static(Lines, "__getitem__") is not _LINES_GETITEM
            or _LINES_GETITEM.__code__ is not _LINES_GETITEM_CODE
        ):
            return None
        if _plain_state(data, _LINE_DICT) is None or _plain_state(lines, _LINES_DICT) is None:
            return None
        raw_lines = inspect.getattr_static(lines, "lines")
        if type(raw_lines) is not list or not raw_lines or type(raw_lines[0]) is not LineBuffer:
            return None
        if _plain_state(raw_lines[0], _LINE_DICT) is None:
            return None
        src = inspect.getattr_static(data, "array")
        dst = inspect.getattr_static(raw_lines[0], "array")
        if not _rolling_eligible(src, dst, start, end, period):
            return None
        return src, dst, period
    except (AttributeError, KeyError, TypeError):
        return None


def _rolling_eligible(src, dst, start, end, period):
    return (
        type(src) is array.array
        and src.typecode == "d"
        and type(dst) is array.array
        and dst.typecode == "d"
        and src is not dst
        and type(start) is int
        and type(end) is int
        and 0 <= start <= end
        and type(period) is int
        and period > 0
    )


def _once_missing_index(src, dst, start, end, period, highest):
    """Write newest extreme index; any NaN in the complete window yields NaN."""
    nan = float("nan")
    while len(dst) < end:
        dst.append(nan)
    candidates = deque()
    missing = 0
    seed = max(0, start - period + 1)
    for index in range(seed, end):
        if index >= len(src):
            if index >= start:
                dst[index] = nan
            continue
        old = index - period
        if old >= seed and src[old] != src[old]:
            missing -= 1
        value = src[index]
        if value != value:
            missing += 1
        else:
            while candidates and (
                value >= src[candidates[-1]] if highest else value <= src[candidates[-1]]
            ):
                candidates.pop()
            candidates.append(index)
        left = index - period + 1
        while candidates and candidates[0] < left:
            candidates.popleft()
        if index >= start:
            dst[index] = nan if index < period - 1 or missing else float(index - candidates[0])


class _MissingAwareFirstIndex:
    __slots__ = ()

    def func(self, iterable):
        if any(value != value for value in iterable):
            return float("nan")
        return super().func(iterable)

    def once(self, start, end):
        cls = type(self)
        if cls is _AroonHighest or cls is _AroonLowest:
            expected = max if cls is _AroonHighest else min
            if (
                _plain_aroon(self, expected)
                and inspect.getattr_static(self, "func") is _MISSING_AWARE_FUNC
                and _MISSING_AWARE_FUNC.__code__ is _MISSING_AWARE_CODE
                and inspect.getattr_static(
                    FindFirstIndexHighest if cls is _AroonHighest else FindFirstIndexLowest, "func"
                )
                is _FIND_FIRST_FUNC
                and _FIND_FIRST_FUNC.__code__ is _FIND_FIRST_CODE
            ):
                inputs = _safe_rolling_inputs(self, start, end)
                if inputs is not None:
                    src, dst, period = inputs
                    _once_missing_index(src, dst, start, end, period, cls is _AroonHighest)
                    return  # noqa: RET502
        return super().once(start, end)


class _AroonHighest(_MissingAwareFirstIndex, FindFirstIndexHighest):
    __slots__ = ()


class _AroonLowest(_MissingAwareFirstIndex, FindFirstIndexLowest):
    __slots__ = ()


_MISSING_AWARE_FUNC = _MissingAwareFirstIndex.func
_MISSING_AWARE_CODE = _MISSING_AWARE_FUNC.__code__
_FAST_CLASS_DICTS = {cls: vars(cls)["__dict__"] for cls in (_AroonHighest, _AroonLowest)}


class _AroonBase(Indicator):
    """
    Base class which does the calculation of the AroonUp/AroonDown values and
    defines the common parameters.

    It uses the class attributes _up and _down (boolean flags) to decide which
    value has to be calculated.

    Values are not assigned to lines but rather stored in the "up" and "down"
    instance variables, which can be used by subclasses to for assignment or
    further calculations
    """

    _up = False
    _down = False

    params = (
        ("period", 14),
        ("upperband", 70),
        ("lowerband", 30),
    )
    plotinfo = {"plotymargin": 0.05, "plotyhlines": [0, 100]}

    def _plotlabel(self):
        plabels = [self.p.period]
        return plabels

    def _plotinit(self):
        self.plotinfo.plotyhlines += [self.p.lowerband, self.p.upperband]

    def __init__(self):
        """Initialize the Aroon base indicator.

        Sets up Aroon Up/Down calculations based on _up and _down flags.
        """
        # Look backwards period + 1 for current data because the formula mus
        # produce values between 0 and 100 and can only do that if the
        # calculated hhidx/llidx go from 0 to period (hence period + 1 values)
        idxperiod = self.p.period + 1

        if self._up:
            hhidx = _AroonHighest(self.data.high, period=idxperiod)
            self.up = (100.0 / self.p.period) * (self.p.period - hhidx)

        if self._down:
            llidx = _AroonLowest(self.data.low, period=idxperiod)
            self.down = (100.0 / self.p.period) * (self.p.period - llidx)

        super().__init__()

    @staticmethod
    def _index_since_extreme(source, index, period, highest):
        """Return bars since the most recent extreme in the period+1 window."""
        if any(source[index - offset] != source[index - offset] for offset in range(period + 1)):
            return float("nan")
        extreme = source[index]
        bars_ago = 0

        for offset in range(1, period + 1):
            value = source[index - offset]
            is_more_extreme = value > extreme if highest else value < extreme
            if is_more_extreme:
                extreme = value
                bars_ago = offset

        return bars_ago

    @classmethod
    def _once_line(cls, source, destination, start, end, period, highest):
        """Calculate one Aroon component directly from its source line array."""
        if (
            any(cls is candidate for candidate in _FAST_AROON_CLASSES)
            and inspect.getattr_static(cls, "_index_since_extreme") is _AROON_INDEX_DESCRIPTOR
            and _AROON_INDEX_DESCRIPTOR.__func__.__code__ is _AROON_INDEX_CODE
            and _rolling_eligible(source, destination, start, end, period)
            and period >= 1
        ):
            _once_missing_index(source, destination, start, end, period + 1, highest)
            for index in range(start, end):
                destination[index] = 100.0 * (period - destination[index]) / period
            return
        while len(destination) < end:
            destination.append(float("nan"))

        for index in range(start, end):
            if index < period or index >= len(source):
                destination[index] = float("nan")
                continue

            bars_ago = cls._index_since_extreme(source, index, period, highest)
            destination[index] = 100.0 * (period - bars_ago) / period


class AroonUp(_AroonBase):
    """
    This is the AroonUp from the indicator AroonUpDown developed by Tushar
    Chande in 1995.

    Formula:
      - up = 100 * (period - distance to the highest high) / period

    Note:
      The lines oscillate between 0 and 100. That means that the "distance" to
      the last highest or lowest must go from 0 to period so that the formula
      can yield 0 and 100.

      Hence, the lookback period is period + 1, because the current bar is also
      taken into account.
      And therefore, this indicator needs an effective
      lookback period of period + 1.

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:aroon
    """

    _up = True

    lines = ("aroonup",)

    def __init__(self):
        """Initialize the Aroon Up indicator.

        Calculates Aroon Up values using parent class logic.
        """
        super().__init__()

    def next(self):
        """Calculate Aroon Up for the current bar.

        Copies the up value from the parent calculation.
        """
        self.lines.aroonup[0] = self.up[0]

    def once(self, start, end):
        """Calculate Aroon Up in runonce mode.

        Computes each value from the source highs for the complete lookback.
        """
        self._once_line(
            self.data.high.array,
            self.lines.aroonup.array,
            start,
            end,
            self.p.period,
            highest=True,
        )


class AroonDown(_AroonBase):
    """
    This is the AroonDown from the indicator AroonUpDown developed by Tushar
    Chande in 1995.

    Formula:
      - down = 100 * (period - distance to the lowest low) / period

    Note:
      The lines oscillate between 0 and 100. That means that the "distance" to
      the last highest or lowest must go from 0 to period so that the formula
      can yield 0 and 100.

      Hence, the lookback period is period + 1, because the current bar is also
      taken into account.
      And therefore, this indicator needs an effective
      lookback period of period + 1.

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:aroon
    """

    _down = True

    lines = ("aroondown",)

    def __init__(self):
        """Initialize the Aroon Down indicator.

        Calculates Aroon Down values using parent class logic.
        """
        super().__init__()

    def next(self):
        """Calculate Aroon Down for the current bar.

        Copies the down value from the parent calculation.
        """
        self.lines.aroondown[0] = self.down[0]

    def once(self, start, end):
        """Calculate Aroon Down in runonce mode.

        Computes each value from the source lows for the complete lookback.
        """
        self._once_line(
            self.data.low.array,
            self.lines.aroondown.array,
            start,
            end,
            self.p.period,
            highest=False,
        )


class AroonUpDown(AroonUp, AroonDown):
    """
    Developed by Tushar Chande in 1995.

    It tries to determine if a trend exists or not by calculating how far away
    within a given period the last highs/lows are (AroonUp/AroonDown)

    Formula:
      - up = 100 * (period - distance to the highest high) / period
      - down = 100 * (period - distance to the lowest low) / period

    Note:
      The lines oscillate between 0 and 100. That means that the "distance" to
      the last highest or lowest must go from 0 to period so that the formula
      can yield 0 and 100.

      Hence, the lookback period is period + 1, because the current bar is also
      taken into account.
      And therefore, this indicator needs an effective
      lookback period of period + 1.

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:aroon
    """

    alias = ("AroonIndicator",)

    def next(self):
        """Calculate each Aroon component exposed by the combined indicator."""
        AroonUp.next(self)
        if "aroondown" in self.lines.getlinealiases():
            self.lines.aroondown[0] = self.down[0]

    def once(self, start, end):
        """Calculate each Aroon component exposed in runonce mode."""
        AroonUp.once(self, start, end)
        if "aroondown" in self.lines.getlinealiases():
            AroonDown.once(self, start, end)


class AroonOscillator(_AroonBase):
    """
    It is a variation of the AroonUpDown indicator which shows the current
    difference between the AroonUp and AroonDown value, trying to present a
    visualization which indicates which is stronger (greater than 0 -> AroonUp
    and less than 0 -> AroonDown)

    Formula:
      - aroonosc = aroonup - aroondown

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:aroon
    """

    _up = True
    _down = True

    alias = ("AroonOsc",)

    lines = ("aroonosc",)

    def _plotinit(self):
        super()._plotinit()

        for yhline in self.plotinfo.plotyhlines[:]:
            self.plotinfo.plotyhlines.append(-yhline)

    def __init__(self):
        """Initialize the Aroon Oscillator indicator.

        Calculates both up and down values for oscillator calculation.
        """
        super().__init__()

    def next(self):
        """Calculate Aroon Oscillator for the current bar.

        Oscillator = Aroon Up - Aroon Down.
        """
        self.lines.aroonosc[0] = self.up[0] - self.down[0]

    def once(self, start, end):
        """Calculate Aroon Oscillator in runonce mode.

        Computes both components from their source arrays and subtracts them.
        """
        high_array = self.data.high.array
        low_array = self.data.low.array
        aroonosc_array = self.lines.aroonosc.array

        period = self.p.period
        if (
            any(type(self) is candidate for candidate in _FAST_AROON_CLASSES)
            and inspect.getattr_static(type(self), "_index_since_extreme")
            is _AROON_INDEX_DESCRIPTOR
            and _AROON_INDEX_DESCRIPTOR.__func__.__code__ is _AROON_INDEX_CODE
            and "_index_since_extreme" not in self.__dict__
            and _rolling_eligible(high_array, aroonosc_array, start, end, period)
            and _rolling_eligible(low_array, aroonosc_array, start, end, period)
        ):
            down = array.array("d", [float("nan")]) * end
            _once_missing_index(high_array, aroonosc_array, start, end, period + 1, True)
            _once_missing_index(low_array, down, start, end, period + 1, False)
            for index in range(start, end):
                up_value = 100.0 * (period - aroonosc_array[index]) / period
                down_value = 100.0 * (period - down[index]) / period
                aroonosc_array[index] = up_value - down_value
            return

        while len(aroonosc_array) < end:
            aroonosc_array.append(float("nan"))

        period = self.p.period
        for index in range(start, end):
            if index < period or index >= len(high_array) or index >= len(low_array):
                aroonosc_array[index] = float("nan")
                continue

            up_bars_ago = self._index_since_extreme(high_array, index, period, highest=True)
            down_bars_ago = self._index_since_extreme(low_array, index, period, highest=False)
            up_value = 100.0 * (period - up_bars_ago) / period
            down_value = 100.0 * (period - down_bars_ago) / period
            aroonosc_array[index] = up_value - down_value


class AroonUpDownOscillator(AroonUpDown, AroonOscillator):
    """
    Presents together the indicators AroonUpDown and AroonOsc

    Formula:
      (None uses the aforementioned indicators)

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:aroon
    """

    alias = ("AroonUpDownOsc",)

    def next(self):
        """Calculate all Aroon outputs currently exposed by the combined class."""
        AroonUpDown.next(self)
        if "aroonosc" in self.lines.getlinealiases():
            self.lines.aroonosc[0] = self.up[0] - self.down[0]

    def once(self, start, end):
        """Calculate all Aroon outputs currently exposed in runonce mode."""
        AroonUpDown.once(self, start, end)
        if "aroonosc" in self.lines.getlinealiases():
            AroonOscillator.once(self, start, end)


_AROON_INDEX_DESCRIPTOR = vars(_AroonBase)["_index_since_extreme"]
_AROON_INDEX_CODE = _AROON_INDEX_DESCRIPTOR.__func__.__code__
_FAST_AROON_CLASSES = (AroonUp, AroonDown, AroonUpDown, AroonOscillator, AroonUpDownOscillator)
