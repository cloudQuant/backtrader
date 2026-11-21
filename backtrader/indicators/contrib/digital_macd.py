#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import array as array_module
from collections import deque
from itertools import islice
import math

try:
    import numpy as _np
except ImportError:  # pragma: no cover - pure Python fallback
    _np = None

from .. import Indicator
from ...linebuffer import LineBuffer, _factor_context_for_line, _read_infinite_line
from ...lineiterator import _clock_is_replaying

__all__ = [
    "DigitalMacd",
]

# Long signal windows use a rolling non-finite count instead of rescanning all entries.
_MIN_SIGNAL_PERIOD_FOR_FINITE_COUNT = 128
# Use NumPy tap-vectorized convolution in once() once a segment is large enough
# to amortize array view setup; smaller segments use the pure-Python fast path.
_MIN_VECTORIZED_ONCE_BARS = 16

# Python 3.12 and newer may use compensated float summation.  The signal
# contract uses Python's sum, while the FIR contract uses ordered +=.
_FLOAT_SUM_COMPENSATED = sum([1.0e16, 1.0, -1.0e16]) != 0.0


def _write_np_slice(line_array, write_start, values):
    """Write a 1D float64 NumPy slice into a Backtrader line buffer array."""
    count = len(values)
    if not count:
        return
    if type(line_array) is array_module.array and line_array.typecode == "d":
        chunk = array_module.array("d")
        chunk.frombytes(_np.ascontiguousarray(values, dtype=_np.float64).tobytes())
        line_array[write_start : write_start + count] = chunk
    else:
        for offset, val in enumerate(values.tolist()):
            line_array[write_start + offset] = val


def _fill_nan_slice(line_array, fill_start, fill_end):
    """Fill ``line_array[fill_start:fill_end]`` with IEEE-754 NaN."""
    count = fill_end - fill_start
    if count <= 0:
        return
    if type(line_array) is array_module.array and line_array.typecode == "d":
        line_array[fill_start:fill_end] = array_module.array("d", [float("nan")]) * count
    else:
        nan_val = float("nan")
        for idx in range(fill_start, fill_end):
            line_array[idx] = nan_val


def _snapshot_plain_line_cells(lines):
    """Capture cells of ordinary LineBuffers reachable through existing bindings."""
    cells = []
    pending = list(lines)
    seen = set()
    while pending:
        line = pending.pop()
        if type(line) is not LineBuffer or id(line) in seen:
            continue
        seen.add(id(line))
        try:
            array = line.array
            index = line.idx
            bindings = line.bindings
        except AttributeError:
            continue
        if type(bindings) in (list, tuple):
            pending.extend(bindings)
        if type(index) is not int or index < 0:
            continue
        if not (
            (type(array) is array_module.array and array.typecode == "d")
            or type(array) in (list, deque)
        ):
            continue
        if index < len(array):
            cells.append((array, "cell", index, array[index]))
        elif type(array) is deque:
            # Appending to a bounded deque may evict existing values.
            cells.append((array, "deque", None, tuple(array)))
        else:
            cells.append((array, "length", len(array), None))
    return cells


def _restore_plain_line_cells(cells):
    """Restore captured built-in storage without invoking binding callbacks."""
    for array, kind, index, value in reversed(cells):
        if kind == "cell":
            if index < len(array):
                array[index] = value
        elif kind == "deque":
            array.clear()
            array.extend(value)
        else:
            del array[index:]


class DigitalMacd(Indicator):
    """Digital MACD indicator built from fixed FIR fast/slow filter banks."""

    lines = ("macd", "signal")
    params = (
        ("signal_period", 5),
        ("point", 0.01),
    )

    FAST_COEFFS = [
        0.2149840610,
        0.2065763732,
        0.1903728890,
        0.1675422436,
        0.1397053150,
        0.1087951881,
        0.0768869405,
        0.0460244906,
        0.0180517395,
        -0.0055294579,
        -0.0236660212,
        -0.0358140055,
        -0.0419497760,
        -0.0425331450,
        -0.0384279507,
        -0.0307917433,
        -0.0209443384,
        -0.0102335925,
        0.0000932767,
        0.0089950015,
        0.0157131144,
        0.0198149331,
        0.0211989019,
        0.0200639819,
        0.0168532934,
        0.0121825067,
        0.0067474241,
        0.0012444305,
        -0.0037087682,
        -0.0076300416,
        -0.0102110543,
        -0.0113306266,
        -0.0110462105,
        -0.0095662166,
        -0.0072080453,
        -0.0043494435,
        -0.0013771970,
        0.0013575268,
        0.0035760416,
        0.0050946166,
        0.0058339574,
        0.0058160431,
        0.0051486631,
        0.0039984014,
        0.0025619380,
        0.0010531475,
        -0.0003481453,
        -0.0014937154,
        -0.0022905986,
        -0.0027000514,
        -0.0027359080,
        -0.0024543322,
        -0.0019409837,
        -0.0012957482,
        -0.0006179734,
        0.0000057542,
        0.0005111297,
        0.0008605279,
        0.0010441921,
        0.0010775684,
        0.0009966494,
        0.0008537300,
        0.0007142855,
        0.0006599146,
        -0.0008151017,
    ]

    SLOW_COEFFS = [
        0.0825641231,
        0.0822783080,
        0.0814249974,
        0.0800166909,
        0.0780735197,
        0.0756232268,
        0.0727009740,
        0.0693478349,
        0.0656105823,
        0.0615409157,
        0.0571939540,
        0.0526285643,
        0.0479025123,
        0.0430785482,
        0.0382152880,
        0.0333706133,
        0.0286021160,
        0.0239614376,
        0.0194972056,
        0.0152532583,
        0.0112682658,
        0.0075745482,
        0.0041980052,
        0.0011588603,
        -0.0015292889,
        -0.0038593393,
        -0.0058303888,
        -0.0074473108,
        -0.0087203043,
        -0.0096645874,
        -0.0102995666,
        -0.0106483424,
        -0.0107374524,
        -0.0105952115,
        -0.0102516944,
        -0.0097377645,
        -0.0090838346,
        -0.0083237046,
        -0.0074804382,
        -0.0065902734,
        -0.0056742995,
        -0.0047554314,
        -0.0038574209,
        -0.0029983549,
        -0.0021924972,
        -0.0014513858,
        -0.0007848072,
        -0.0001995891,
        0.0003009728,
        0.0007162164,
        0.0010478905,
        0.0012994016,
        0.0014755433,
        0.0015824007,
        0.0016272598,
        0.0016185271,
        0.0015648336,
        0.0014747659,
        0.0013569946,
        0.0012193896,
        0.0010695971,
        0.0009140878,
        0.0007591540,
        0.0016019033,
    ]

    def __init__(self):
        """Cache FIR coefficients, set warmup, and build the signal SMA.

        Side effects:
            Stores the fast/slow coefficient tuples, allocates the rolling close
            buffer, sets the minimum warmup period, and wires ``signal`` as an
            SMA of the ``macd`` line.
        """
        self._fast_coeffs = tuple(float(v) for v in self.FAST_COEFFS)
        self._slow_coeffs = tuple(float(v) for v in self.SLOW_COEFFS)
        self._max_lookback = max(len(self._fast_coeffs), len(self._slow_coeffs))
        self._closes = deque(maxlen=self._max_lookback)
        self._signal_period = max(int(self.p.signal_period), 1)
        self._signal_history = deque(maxlen=self._signal_period)
        self._track_signal_finite_count = (
            self._signal_period >= _MIN_SIGNAL_PERIOD_FOR_FINITE_COUNT
        )
        self._signal_nonfinite_count = 0
        self._last_source_length = None
        self.addminperiod(self._max_lookback + self._signal_period - 1)
        self._point = float(self.p.point) if float(self.p.point) else 1.0

    def _uses_builtin_step(self):
        """Return whether batch ``preonce``/``once`` may bypass per-bar ``next``."""
        # Direct array writes bypass strict factor line validation.  Keep the
        # established per-bar path when that validation is active.
        if any(_factor_context_for_line(line) is not None for line in self.lines):
            return False
        if (
            getattr(type(self), "next", None) is not _DEFAULT_DIGITAL_MACD_NEXT
            or getattr(type(self), "prenext", None) is not _DEFAULT_DIGITAL_MACD_PRENEXT
            or getattr(type(self), "nextstart", None) is not _DEFAULT_DIGITAL_MACD_NEXTSTART
        ):
            return False
        try:
            inst_dict = object.__getattribute__(self, "__dict__")
        except AttributeError:
            return True
        return (
            "next" not in inst_dict
            and "prenext" not in inst_dict
            and "nextstart" not in inst_dict
        )

    def prenext(self):
        """Build FIR and signal history while the full output is warming up."""
        self.next()

    def next(self):
        """Convolve closes and calculate the signal from actual MACD history.

        Emits NaN until the buffer is full, then writes the point-scaled
        difference of the fast and slow digital filter outputs to ``macd``.
        The signal is the simple average of the latest finite MACD window.
        """
        source_length = len(self.data)
        revising = self._last_source_length == source_length
        if revising and not _clock_is_replaying(self.data):
            return

        # Build the proposed histories separately.  A replay revision can
        # fail on the input read or on either output write; in that case its
        # previously accepted bar must remain available for a same-bar retry.
        close = float(self.data.close[0])
        closes = tuple(self._closes)
        history = self._signal_history
        history_start = 0
        history_stop = len(history)
        nonfinite_count = self._signal_nonfinite_count
        if revising:
            closes = closes[:-1]
            if history:
                if self._track_signal_finite_count and not math.isfinite(history[-1]):
                    nonfinite_count -= 1
                history_stop -= 1
        elif len(history) == self._signal_period:
            history_start = 1
            if self._track_signal_finite_count and not math.isfinite(history[0]):
                nonfinite_count -= 1
        closes = (closes + (close,))[-self._max_lookback :]
        if len(closes) < self._max_lookback:
            macd = float("nan")
        else:
            fast_dma = 0.0
            for idx, coeff in enumerate(self._fast_coeffs):
                fast_dma += coeff * closes[-(idx + 1)]
            slow_dma = 0.0
            for idx, coeff in enumerate(self._slow_coeffs):
                slow_dma += coeff * closes[-(idx + 1)]
            macd = (fast_dma - slow_dma) / self._point

        history_length = history_stop - history_start + 1
        if self._track_signal_finite_count:
            if not math.isfinite(macd):
                nonfinite_count += 1
            ready = history_length == self._signal_period and not nonfinite_count
        else:
            ready = (
                history_length == self._signal_period
                and all(math.isfinite(value) for value in islice(history, history_start, history_stop))
                and math.isfinite(macd)
            )
        if ready:
            # A copy is needed only for a complete finite window.  Keep a
            # deque so sum uses the same order and semantics as next().
            candidate_history = history.copy()
            if revising and candidate_history:
                candidate_history.pop()
            candidate_history.append(macd)
            signal = sum(candidate_history) / self._signal_period
        else:
            signal = float("nan")

        # Ordinary LineBuffer bindings propagate writes recursively. Snapshot
        # those cells too; arbitrary custom binding side effects are not
        # reversible and are intentionally outside this guarantee.
        output_cells = _snapshot_plain_line_cells((self.l.macd, self.l.signal))
        try:
            self.l.macd[0] = macd
            self.l.signal[0] = signal
        except BaseException:
            _restore_plain_line_cells(output_cells)
            raise

        if revising:
            if self._closes:
                self._closes.pop()
            if self._signal_history:
                self._signal_history.pop()
        self._closes.append(close)
        self._signal_history.append(macd)
        self._signal_nonfinite_count = nonfinite_count
        self._last_source_length = source_length

    def preonce(self, start, end):
        """Compute FIR MACD outputs during warmup in runonce mode."""
        if not self._uses_builtin_step():
            self.preonce_via_prenext(start, end)
            return
        self._compute_once_range(start, end)

    def oncestart(self, start, end):
        """Compute the first post-warmup bar in runonce mode."""
        if not self._uses_builtin_step():
            self.oncestart_via_nextstart(start, end)
            return
        self._compute_once_range(start, end)

    def once(self, start, end):
        """Compute FIR MACD and signal arrays over ``[start, end)`` in runonce mode."""
        if not self._uses_builtin_step():
            self.once_via_next(start, end)
            return
        self._compute_once_range(start, end)

    def _compute_once_range(self, start, end):
        """Evaluate ``macd`` and ``signal`` over ``[start, end)`` bit-exact to ``next``."""
        start = max(0, int(start))
        end = int(end)
        if end <= start:
            return

        macd_line = self.l.macd.array
        signal_line = self.l.signal.array
        nan_val = float("nan")
        for line_array in (macd_line, signal_line):
            deficit = end - len(line_array)
            if deficit > 0:
                if type(line_array) is array_module.array and line_array.typecode == "d":
                    line_array.extend(array_module.array("d", [nan_val]) * deficit)
                else:
                    line_array.extend([nan_val] * deficit)

        close_line = self.data.close
        close_array = close_line.array
        actual_end = min(end, len(close_array))
        if actual_end <= start:
            _fill_nan_slice(macd_line, start, end)
            _fill_nan_slice(signal_line, start, end)
            return

        lookback = self._max_lookback
        signal_period = self._signal_period
        point = self._point
        fast_coeffs = self._fast_coeffs
        slow_coeffs = self._slow_coeffs

        macd_write_start = max(start, lookback - 1)
        sig_write_start = max(start, lookback - 1 + signal_period - 1)

        if macd_write_start >= actual_end:
            _fill_nan_slice(macd_line, start, end)
            _fill_nan_slice(signal_line, start, end)
            return

        if sig_write_start < actual_end:
            macd_calc_start = min(macd_write_start, sig_write_start - signal_period + 1)
        else:
            macd_calc_start = macd_write_start

        src_start = macd_calc_start - (lookback - 1)
        calc_count = actual_end - macd_calc_start

        if start < macd_write_start:
            _fill_nan_slice(macd_line, start, macd_write_start)
        sig_nan_end = min(actual_end, sig_write_start)
        if start < sig_nan_end:
            _fill_nan_slice(signal_line, start, sig_nan_end)
        if actual_end < end:
            _fill_nan_slice(macd_line, actual_end, end)
            _fill_nan_slice(signal_line, actual_end, end)

        if _np is not None and calc_count >= _MIN_VECTORIZED_ONCE_BARS:
            if type(close_array) is array_module.array and close_array.typecode == "d":
                src = _np.frombuffer(close_array, dtype=_np.float64)[src_start:actual_end]
            else:
                src = _np.asarray(
                    [float(close_array[idx]) for idx in range(src_start, actual_end)],
                    dtype=_np.float64,
                )
            if _np.any(_np.isinf(src)):
                src = _np.asarray(
                    [
                        float(_read_infinite_line(close_line, float(val)))
                        if math.isinf(val)
                        else float(val)
                        for val in src
                    ],
                    dtype=_np.float64,
                )

            src_len = len(src)
            # Vectorize across bars while keeping exact tap-order accumulation
            # (0..len-1) so every output matches next() bit-for-bit.
            with _np.errstate(all="ignore"):
                fast_acc = _np.zeros(calc_count, dtype=_np.float64)
                for tap, coeff in enumerate(fast_coeffs):
                    fast_acc += coeff * src[lookback - 1 - tap : src_len - tap]
                slow_acc = _np.zeros(calc_count, dtype=_np.float64)
                for tap, coeff in enumerate(slow_coeffs):
                    slow_acc += coeff * src[lookback - 1 - tap : src_len - tap]
                m_vec = (fast_acc - slow_acc) / point
                m_vec = _np.where(_np.isfinite(m_vec), m_vec, _np.nan)

            _write_np_slice(
                macd_line,
                macd_write_start,
                m_vec[macd_write_start - macd_calc_start :],
            )

            if sig_write_start < actual_end:
                sig_count = actual_end - sig_write_start
                sig_base = sig_write_start - signal_period + 1 - macd_calc_start
                if _FLOAT_SUM_COMPENSATED:
                    # Match next(): Python's sum may use compensated float
                    # accumulation, which vectorized += does not reproduce.
                    macd_values = m_vec.tolist()
                    sig_vec = []
                    for idx in range(sig_count):
                        window = macd_values[sig_base + idx : sig_base + idx + signal_period]
                        if all(math.isfinite(value) for value in window):
                            value = sum(window) / signal_period
                            sig_vec.append(value if math.isfinite(value) else nan_val)
                        else:
                            sig_vec.append(nan_val)
                    sig_vec = _np.asarray(sig_vec, dtype=_np.float64)
                else:
                    with _np.errstate(all="ignore"):
                        sig_acc = _np.zeros(sig_count, dtype=_np.float64)
                        for offset in range(signal_period):
                            sig_acc += m_vec[sig_base + offset : sig_base + offset + sig_count]
                        sig_vec = sig_acc / float(signal_period)
                        sig_vec = _np.where(_np.isfinite(sig_vec), sig_vec, _np.nan)
                _write_np_slice(signal_line, sig_write_start, sig_vec)
            return

        # Pure-Python fast path for short segments (e.g. oncestart) or no-NumPy environments.
        src_list = [float(close_array[idx]) for idx in range(src_start, actual_end)]
        for idx, val in enumerate(src_list):
            if math.isinf(val):
                src_list[idx] = float(_read_infinite_line(close_line, val))

        m_vals = [nan_val] * calc_count
        for offset in range(calc_count):
            pos = lookback - 1 + offset
            window = (
                src_list[pos : pos - lookback : -1]
                if pos >= lookback
                else src_list[pos::-1]
            )
            fast_dma = 0.0
            for idx, coeff in enumerate(fast_coeffs):
                fast_dma += coeff * window[idx]
            slow_dma = 0.0
            for idx, coeff in enumerate(slow_coeffs):
                slow_dma += coeff * window[idx]
            val = (fast_dma - slow_dma) / point
            if math.isfinite(val):
                m_vals[offset] = val

        macd_slice_start = macd_write_start - macd_calc_start
        for offset in range(macd_slice_start, calc_count):
            macd_line[macd_calc_start + offset] = m_vals[offset]

        if sig_write_start < actual_end:
            sig_count = actual_end - sig_write_start
            sig_base = sig_write_start - signal_period + 1 - macd_calc_start
            nonfinite_count = sum(
                1
                for item in m_vals[sig_base : sig_base + signal_period]
                if not math.isfinite(item)
            )
            for idx in range(sig_count):
                if idx > 0:
                    if not math.isfinite(m_vals[sig_base + idx - 1]):
                        nonfinite_count -= 1
                    if not math.isfinite(m_vals[sig_base + idx + signal_period - 1]):
                        nonfinite_count += 1
                if nonfinite_count:
                    signal_line[sig_write_start + idx] = nan_val
                else:
                    sig_val = (
                        sum(m_vals[sig_base + idx : sig_base + idx + signal_period])
                        / signal_period
                    )
                    signal_line[sig_write_start + idx] = (
                        sig_val if math.isfinite(sig_val) else nan_val
                    )


_DEFAULT_DIGITAL_MACD_NEXT = DigitalMacd.next
_DEFAULT_DIGITAL_MACD_PRENEXT = DigitalMacd.prenext
_DEFAULT_DIGITAL_MACD_NEXTSTART = DigitalMacd.nextstart
