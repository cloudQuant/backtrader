#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import array as array_module
from collections import deque

from .. import Indicator
from ...linebuffer import LineBuffer, _ACTIVE_FACTOR_CONTEXT, _factor_context_for_line
from ...parameters import ParameterAccessor, ParameterManager


class _ProjectedHistory:
    """Read an absolute source slot through its normal line access policy."""

    def __init__(self, line, position):
        self.line = line
        self.position = position

    def __getitem__(self, index):
        return self.line[index - self.position]


__all__ = [
    "StochasticHistogramIndicator",
]


def _check_strict_ma(self, values, period, previous, mode, value, context):
    """Check native intermediate floats before a later NaN can hide overflow."""
    from ...research.strict import reject_infinity

    def check(result):
        reject_infinity(context, result, context.phase, operation=self.lines.main)
        return result

    if mode in {"ema", "mode_ema"} and previous is not None and previous == previous:
        delta = check(value - previous)
        weighted = check((2.0 / (period + 1.0)) * delta)
        check(previous + weighted)
    elif mode in {"smma", "mode_smma"} and previous is not None and previous == previous:
        weighted = check((period - 1.0) * previous)
        check(weighted + value)
    elif mode in {"lwma", "wma", "mode_lwma"}:
        total = 0.0
        for weight, item in enumerate(values, 1):
            total = check(total + check(item * weight))
    elif mode not in {"ema", "mode_ema", "smma", "mode_smma"}:
        total = 0.0
        for item in values:
            total = check(total + item)


class StochasticHistogramIndicator(Indicator):
    """Stochastic-based indicator with a smoothed main line, signal line, and color state.

    The indicator outputs:
    - ``main``: smoothed %K values.
    - ``signal``: smoothed trigger line derived from main.
    - ``hist_base``: fixed base reference line (50.0).
    - ``color_state``: 0 for overbought, 1 for neutral, 2 for oversold.
    """

    lines = ("main", "signal", "hist_base", "color_state")
    params = (
        ("k_period", 5),
        ("d_period", 3),
        ("slowing", 3),
        ("ma_method", "sma"),
        ("high_level", 60),
        ("low_level", 40),
    )

    def __init__(self):
        """Set the minimum required bars from K, slowing, and D periods."""
        self.addminperiod(int(self.p.k_period) + int(self.p.slowing) + int(self.p.d_period) + 2)
        self._stream_initial_params = (
            self.p.k_period,
            self.p.slowing,
            self.p.d_period,
            self.p.ma_method,
        )
        self._stream_state_params = None
        self._stream_state_count = 0
        self._stream_fast_values = None
        self._stream_main_values = None
        self._stream_prev_main = None
        self._stream_prev_signal = None
        self._stream_state_index = None
        self._stream_before_current = None
        self._stream_main = float("nan")
        self._stream_signal = float("nan")
        self._stream_force_legacy = False

    def _fast_k_at(self, i, high_array, low_array, close_array):
        period = max(1, int(self.p.k_period))
        if i - period + 1 < 0:
            return float("nan")
        lowest = min(float(low_array[idx]) for idx in range(i - period + 1, i + 1))
        highest = max(float(high_array[idx]) for idx in range(i - period + 1, i + 1))
        denom = highest - lowest
        return 100.0 * (float(close_array[i]) - lowest) / denom if denom else 50.0

    def _ma_value(self, values, period, previous=None):
        if not values:
            return float("nan")
        mode = str(self.p.ma_method).strip().lower()
        value = float(values[-1])
        context = _ACTIVE_FACTOR_CONTEXT.get()
        if (
            context is not None
            and type(period) is int
            and (previous is None or type(previous) is float)
            and all(type(item) is float for item in values)
        ):
            _check_strict_ma(self, values, period, previous, mode, value, context)
        if mode in {"ema", "mode_ema"}:
            if previous is None or previous != previous:
                return value
            alpha = 2.0 / (period + 1.0)
            return previous + alpha * (value - previous)
        if mode in {"smma", "mode_smma"}:
            if previous is None or previous != previous:
                return value
            return ((period - 1.0) * previous + value) / period
        if mode in {"lwma", "wma", "mode_lwma"}:
            weights = list(range(1, len(values) + 1))
            return sum(v * w for v, w in zip(values, weights)) / sum(weights)
        return sum(values) / len(values)

    def _streaming_state_compatible(self):
        """Return whether private warm-up state preserves the active hooks."""
        if (
            vars(ParameterAccessor).get("__getattribute__") is not _PARAM_GETATTRIBUTE
            or _PARAM_GETATTRIBUTE.__code__ is not _PARAM_GETATTRIBUTE_CODE
            or vars(ParameterManager).get("get") is not _PARAM_MANAGER_GET
            or _PARAM_MANAGER_GET.__code__ is not _PARAM_MANAGER_GET_CODE
            or _PARAM_MANAGER_GET.__defaults__ is not _PARAM_MANAGER_GET_DEFAULTS
        ):
            return False
        if not isinstance(self, StochasticHistogramIndicator):
            return False
        if type(self).__getattribute__ is not _DEFAULT_INSTANCE_GETATTRIBUTE:
            return False
        if getattr(self, "_stream_force_legacy", True):
            return False
        if not hasattr(self, "_stream_initial_params"):
            return False

        for name, original in _DEFAULT_STREAM_HOOKS.items():
            method = getattr(self, name)
            if getattr(method, "__func__", None) is not original:
                return False

        if getattr(self.prenext, "__func__", None) is not _DEFAULT_PARENT_PRENEXT:
            return False
        if getattr(self.nextstart, "__func__", None) is not _DEFAULT_PARENT_NEXTSTART:
            return False

        params = self._stream_params()
        if params is None or params != self._stream_initial_params:
            self._stream_force_legacy = True
            return False
        if self._stream_state_params is not None and params != self._stream_state_params:
            self._stream_force_legacy = True
            return False

        return True

    def _stream_params(self):
        """Use the bounded state only for ordinary immutable scalar params."""
        params = (
            self.p.k_period,
            self.p.slowing,
            self.p.d_period,
            self.p.ma_method,
        )
        if any(type(value) is not int for value in params[:3]) or type(params[3]) is not str:
            return None
        return params

    def _compute_stream_step(self):
        """Compute bounded recurrence state for a streaming bar without committing.

        Returns a candidate state tuple on success, or ``None`` if streaming
        state cannot safely represent the source buffer transition and the
        caller should fall back to :meth:`_next_legacy`.
        """
        data_count = len(self.data)
        if not data_count:
            return None

        source_lines = (self.data.high, self.data.low, self.data.close)
        if any(
            type(line).__getattribute__ is not _DEFAULT_LINEBUFFER_GETATTRIBUTE
            or getattr(type(line), "idx", None) is not _DEFAULT_LINEBUFFER_IDX
            or getattr(type(line), "get_idx", None) is not _DEFAULT_LINEBUFFER_GET_IDX
            or len(line) != data_count
            for line in source_lines
        ):
            self._stream_force_legacy = True
            return None

        high_array, low_array, close_array = (line.array for line in source_lines)
        if any(
            type(buffer) not in (array_module.array, deque)
            for buffer in (high_array, low_array, close_array)
        ):
            self._stream_force_legacy = True
            return None
        high_index, low_index, close_index = (line.idx for line in source_lines)
        if high_index != low_index or high_index != close_index or high_index < 0:
            self._stream_force_legacy = True
            return None

        params = self._stream_params()
        if params is None or params != self._stream_initial_params:
            self._stream_force_legacy = True
            return None

        k_period = max(1, int(self.p.k_period))
        slowing = max(1, int(self.p.slowing))
        d_period = max(1, int(self.p.d_period))

        if self._stream_state_params is None:
            # The first streaming callback is at the indicator minperiod. Its
            # retained source prefix must still start at bar zero; otherwise a
            # bounded/late-start source cannot reproduce once's recurrence.
            if high_index + 1 != data_count:
                self._stream_force_legacy = True
                return None
            fast_values = deque(maxlen=slowing)
            main_values = deque(maxlen=d_period)
            prev_main = None
            prev_signal = None
            start = 0
            end = high_index + 1
        else:
            if params != self._stream_state_params:
                self._stream_force_legacy = True
                return None
            if data_count == self._stream_state_count:
                # A secondary clock may call the strategy again without moving
                # this feed. Replay may also revise the current bar in place
                # (in QBuffer replay with extrasize>0, revising the bar after a
                # new bar pops the extra slot and shifts idx down by 1).
                # Recompute from the state before this bar so both cases are
                # idempotent and do not advance EMA/SMMA state twice.
                same_idx = high_index == self._stream_state_index
                qbuffer_replay_shift = (
                    high_index == self._stream_state_index - 1
                    and high_index + 1 >= k_period
                    and all(
                        line.mode == LineBuffer.QBuffer
                        and line.extrasize > 0
                        and line.idx == len(line.array) - 1
                        for line in source_lines
                    )
                )
                if not (same_idx or qbuffer_replay_shift) or self._stream_before_current is None:
                    self._stream_force_legacy = True
                    return None
                saved_fast, saved_main, prev_main, prev_signal = self._stream_before_current
                fast_values = saved_fast.copy()
                main_values = saved_main.copy()
                start = high_index
                end = high_index + 1
            elif data_count == self._stream_state_count + 1:
                # In UnBounded mode (and QBuffer before saturation), ``idx``
                # advances by 1 with ``data_count``. Once a QBuffer reaches
                # ``lenmark`` (e.g. ``exactbars=1``), ``deque(maxlen=...)``
                # shifts left while ``idx`` stays pinned at ``lenmark``; the
                # newly appended bar sits at ``idx`` and retains at least
                # ``idx + 1`` chronological bars.
                advanced_idx = high_index == self._stream_state_index + 1
                saturated_qbuffer = (
                    high_index == self._stream_state_index
                    and high_index + 1 >= k_period
                    and all(
                        line.mode == LineBuffer.QBuffer and line.idx == line.lenmark
                        for line in source_lines
                    )
                )
                if not (advanced_idx or saturated_qbuffer):
                    self._stream_force_legacy = True
                    return None
                fast_values = self._stream_fast_values.copy()
                main_values = self._stream_main_values.copy()
                prev_main = self._stream_prev_main
                prev_signal = self._stream_prev_signal
                start = high_index
                end = high_index + 1
            else:
                # Rewinds and skipped source bars cannot be reconstructed from
                # the bounded state. Preserve the historical line path there.
                self._stream_force_legacy = True
                return None

        if end > min(len(high_array), len(low_array), len(close_array)):
            self._stream_force_legacy = True
            return None

        before_current = None
        main = None
        signal = None
        projected_high, projected_low, projected_close = (
            _ProjectedHistory(line, high_index) for line in source_lines
        )
        for index in range(start, end):
            before_current = (
                fast_values.copy(),
                main_values.copy(),
                prev_main,
                prev_signal,
            )
            fast = self._fast_k_at(index, projected_high, projected_low, projected_close)
            fast_values.append(fast)
            main = self._ma_value(
                list(fast_values),
                slowing,
                prev_main,
            )
            main_values.append(main)
            signal = self._ma_value(
                list(main_values),
                d_period,
                prev_signal,
            )
            prev_main = main
            prev_signal = signal

        if main is None:
            self._stream_force_legacy = True
            return None

        return (
            params,
            fast_values,
            main_values,
            prev_main,
            prev_signal,
            before_current,
            main,
            signal,
            data_count,
            high_index,
        )

    def _next_legacy(self):
        """Run the original line-based path for subclasses and dynamic params."""
        k_period = max(1, int(self.p.k_period))
        slowing = max(1, int(self.p.slowing))
        d_period = max(1, int(self.p.d_period))
        fast_values = []
        context = _ACTIVE_FACTOR_CONTEXT.get()
        if context is not None:
            from ...research.strict import reject_infinity
        for ago in range(slowing - 1, -1, -1):
            if len(self.data) <= ago + k_period - 1:
                return
            low_values = [float(self.data.low[-ago - shift]) for shift in range(k_period)]
            high_values = [float(self.data.high[-ago - shift]) for shift in range(k_period)]
            lowest = min(low_values)
            highest = max(high_values)
            denom = highest - lowest
            if context is None:
                fast_values.append(
                    100.0 * (float(self.data.close[-ago]) - lowest) / denom if denom else 50.0
                )
            else:
                reject_infinity(context, denom, context.phase, operation=self.lines.main)
                if denom:
                    delta = float(self.data.close[-ago]) - lowest
                    reject_infinity(context, delta, context.phase, operation=self.lines.main)
                    numerator = 100.0 * delta
                    reject_infinity(context, numerator, context.phase, operation=self.lines.main)
                    fast = numerator / denom
                    reject_infinity(context, fast, context.phase, operation=self.lines.main)
                    fast_values.append(fast)
                else:
                    fast_values.append(50.0)
        prev_main = float(self.lines.main[-1]) if len(self) > 1 else None
        prev_signal = float(self.lines.signal[-1]) if len(self) > 1 else None
        main = self._ma_value(fast_values, slowing, prev_main)
        self.lines.main[0] = main
        signal_values = [
            float(self.lines.main[-ago]) for ago in range(min(len(self), d_period) - 1, 0, -1)
        ]
        signal_values.append(main)
        self.lines.signal[0] = self._ma_value(signal_values, d_period, prev_signal)
        color = 1.0
        if main > float(self.p.high_level):
            color = 0.0
        elif main < float(self.p.low_level):
            color = 2.0
        self.lines.color_state[0] = color
        self.lines.hist_base[0] = 50.0

    def next(self):
        """Compute one bar, reusing the private warm-up recurrence when safe.

        If writing any output line raises, previously written current-bar output
        slots are restored on a best-effort basis and the bounded streaming
        state remains at the last committed bar/revision.
        """
        if any(
            _factor_context_for_line(line) is not None
            for line in (
                self.lines.main,
                self.lines.signal,
                self.lines.hist_base,
                self.lines.color_state,
                self.data.high,
                self.data.low,
                self.data.close,
            )
        ):
            if self._stream_state_params is not None:
                self._stream_force_legacy = True
            return self._next_legacy()
        if not self._streaming_state_compatible():
            return self._next_legacy()

        # A custom threshold conversion can mutate the just-written lines.
        # The historical path observes those writes on the next bar; cached
        # smoothing state cannot assume it can reproduce that feedback.
        if type(self.p.high_level) not in (int, float) or type(self.p.low_level) not in (int, float):
            self._stream_force_legacy = True
            return self._next_legacy()

        step = self._compute_stream_step()
        if step is None:
            return self._next_legacy()

        (
            params,
            fast_values,
            main_values,
            prev_main,
            prev_signal,
            before_current,
            main,
            signal,
            data_count,
            high_index,
        ) = step

        output_lines = (
            self.lines.main,
            self.lines.signal,
            self.lines.color_state,
            self.lines.hist_base,
        )
        previous_outputs = tuple(line[0] for line in output_lines)
        written = 0
        try:
            for line, value in zip(output_lines[:2], (main, signal)):
                written += 1
                line[0] = value
            color = 1.0
            if main > float(self.p.high_level):
                color = 0.0
            elif main < float(self.p.low_level):
                color = 2.0
            for line, value in zip(output_lines[2:], (color, 50.0)):
                written += 1
                line[0] = value
        except BaseException:
            for line, old_value in zip(output_lines[:written], previous_outputs[:written]):
                try:
                    line[0] = old_value
                except BaseException:
                    # Best-effort rollback: keep the original write exception
                    # authoritative if restoring a line slot also fails.
                    pass
            raise

        self._stream_state_params = params
        self._stream_fast_values = fast_values
        self._stream_main_values = main_values
        self._stream_prev_main = prev_main
        self._stream_prev_signal = prev_signal
        self._stream_before_current = before_current
        self._stream_main = main
        self._stream_signal = signal
        self._stream_state_count = data_count
        self._stream_state_index = high_index

    def _once_strict_from_next(self, start, end):
        lines = list(self.data.lines) + list(self.lines)
        unique = list({id(line): line for line in lines}.values())
        saved = [(line, line._idx, line.lencount) for line in unique]
        try:
            for i in range(start, end):
                for line in unique:
                    line._idx = i
                    line.lencount = i + 1
                self.next()
        finally:
            for line, index, count in saved:
                line._idx = index
                line.lencount = count

    def once(self, start, end):
        """Compute indicator arrays for run-once mode from ``start`` to ``end`` indices."""
        if (
            _ACTIVE_FACTOR_CONTEXT.get() is not None
            and type(self) is StochasticHistogramIndicator
            and all(
                getattr(getattr(self, name), "__func__", None) is method
                and method.__code__ is code
                for name, (method, code) in _STRICT_ONCE_HOOKS.items()
            )
            and vars(ParameterAccessor).get("__getattribute__") is _PARAM_GETATTRIBUTE
            and _PARAM_GETATTRIBUTE.__code__ is _PARAM_GETATTRIBUTE_CODE
            and vars(ParameterManager).get("get") is _PARAM_MANAGER_GET
            and _PARAM_MANAGER_GET.__code__ is _PARAM_MANAGER_GET_CODE
            and _PARAM_MANAGER_GET.__defaults__ is _PARAM_MANAGER_GET_DEFAULTS
            and type(self.p.k_period) is int
            and type(self.p.slowing) is int
            and type(self.p.d_period) is int
            and type(self.p.ma_method) is str
            and type(self.p.high_level) in (int, float)
            and type(self.p.low_level) in (int, float)
        ):
            return self._once_strict_from_next(start, end)
        high_array = self.data.high.array
        low_array = self.data.low.array
        close_array = self.data.close.array
        main_line = self.lines.main.array
        signal_line = self.lines.signal.array
        hist_base_line = self.lines.hist_base.array
        color_state_line = self.lines.color_state.array
        for line in (main_line, signal_line, hist_base_line, color_state_line):
            while len(line) < end:
                line.append(float("nan"))

        slowing = max(1, int(self.p.slowing))
        d_period = max(1, int(self.p.d_period))
        actual_end = min(end, len(high_array), len(low_array), len(close_array))
        fast_values = [
            self._fast_k_at(i, high_array, low_array, close_array) for i in range(actual_end)
        ]
        main_values = []
        signal_values_all = []
        prev_main = None
        prev_signal = None
        for i in range(actual_end):
            main_start = max(0, i - slowing + 1)
            main = self._ma_value(fast_values[main_start : i + 1], slowing, prev_main)
            main_values.append(main)
            prev_main = main
            signal_start = max(0, i - d_period + 1)
            signal = self._ma_value(main_values[signal_start : i + 1], d_period, prev_signal)
            signal_values_all.append(signal)
            prev_signal = signal
            if i < start:
                continue
            main_line[i] = main
            signal_line[i] = signal_values_all[i]
            color = 1.0
            if main > float(self.p.high_level):
                color = 0.0
            elif main < float(self.p.low_level):
                color = 2.0
            color_state_line[i] = color
            hist_base_line[i] = 50.0


_DEFAULT_PARENT_PRENEXT = Indicator.prenext
_DEFAULT_PARENT_NEXTSTART = Indicator.nextstart
_PARAM_GETATTRIBUTE = ParameterAccessor.__getattribute__
_PARAM_GETATTRIBUTE_CODE = _PARAM_GETATTRIBUTE.__code__
_PARAM_MANAGER_GET = ParameterManager.get
_PARAM_MANAGER_GET_CODE = _PARAM_MANAGER_GET.__code__
_PARAM_MANAGER_GET_DEFAULTS = _PARAM_MANAGER_GET.__defaults__
_DEFAULT_INSTANCE_GETATTRIBUTE = StochasticHistogramIndicator.__getattribute__
_DEFAULT_LINEBUFFER_GETATTRIBUTE = LineBuffer.__getattribute__
_DEFAULT_LINEBUFFER_IDX = LineBuffer.idx
_DEFAULT_LINEBUFFER_GET_IDX = LineBuffer.get_idx
_DEFAULT_STREAM_HOOKS = {
    "_fast_k_at": StochasticHistogramIndicator._fast_k_at,
    "_ma_value": StochasticHistogramIndicator._ma_value,
    "next": StochasticHistogramIndicator.next,
    "once": StochasticHistogramIndicator.once,
}

_STRICT_ONCE_HOOKS = {
    name: (method, method.__code__)
    for name, method in {
        "next": StochasticHistogramIndicator.next,
        "_next_legacy": StochasticHistogramIndicator._next_legacy,
        "_fast_k_at": StochasticHistogramIndicator._fast_k_at,
        "_ma_value": StochasticHistogramIndicator._ma_value,
    }.items()
}
