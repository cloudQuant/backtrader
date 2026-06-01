#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import re
from collections import deque
from pathlib import Path

from .. import Indicator

__all__ = [
    "MovingAverageFNIndicator",
]


SOURCE_MQ5 = (
    Path(__file__).resolve().parents[2]
    / "ea"
    / "1276_Exp_MovingAverage_FN"
    / "movingaverage_fn.mq5"
)


def resolve_price_line(data, mode):
    """Return the price line selected by an MT5 applied-price mode.

    Args:
        data: The data feed providing OHLC lines.
        mode: Applied-price mode name (e.g. ``price_close``, ``price_median``).

    Returns:
        The line or line expression for the requested applied price; defaults
        to the close line for unrecognized modes.
    """
    price_mode = str(mode).lower()
    if price_mode in {"price_open", "open"}:
        return data.open
    if price_mode in {"price_high", "high"}:
        return data.high
    if price_mode in {"price_low", "low"}:
        return data.low
    if price_mode in {"price_median", "median"}:
        return (data.high + data.low) / 2.0
    if price_mode in {"price_typical", "typical"}:
        return (data.high + data.low + data.close) / 3.0
    if price_mode in {"price_weighted", "weighted"}:
        return (data.high + data.low + data.close + data.close) / 4.0
    return data.close


def load_fn_coefficients(filter_name="N44"):
    """Parse FIR filter coefficients for a named filter from the MQ5 source.

    Args:
        filter_name: Filter case name (e.g. ``N44``) to extract.

    Returns:
        List of float coefficients ordered by price-series offset; ``[1.0]`` if
        the source file is missing.

    Raises:
        ValueError: If the filter or the following case marker is not found.
    """
    if not SOURCE_MQ5.exists():
        return [1.0]
    raw = SOURCE_MQ5.read_bytes()
    candidates = []
    for encoding in ("utf-16", "utf-16-le", "utf-8", "latin-1"):
        try:
            candidates.append(raw.decode(encoding, errors="ignore"))
        except Exception:
            continue
    text = ""
    for candidate in candidates:
        normalized = candidate.replace("\x00", "")
        if f"case {filter_name}:" in normalized:
            text = normalized
            break
    if not text:
        text = raw.decode("latin-1", errors="ignore").replace("\x00", "")
    start = text.find(f"case {filter_name}:")
    if start == -1:
        raise ValueError(f"Filter {filter_name} not found in {SOURCE_MQ5}")
    next_case = re.search(r"\n\s*case\s+N\d+:", text[start + 1 :])
    if not next_case:
        raise ValueError(f"Could not locate next filter after {filter_name}")
    block = text[start : start + 1 + next_case.start()]
    matches = re.findall(
        r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\*PriceSeries\(Price,index(?:-(\d+))?", block
    )
    coeff_map = {int(offset or "0"): float(coef) for coef, offset in matches}
    coeffs = [coeff_map[i] for i in range(max(coeff_map) + 1)]
    return coeffs


class MovingAverageFNIndicator(Indicator):
    """FIR moving average built from named filter coefficients plus smoothing."""

    lines = ("mafn",)
    params = (
        ("filter_number", "N44"),
        ("xma_method", "jjma"),
        ("xlength", 12),
        ("xphase", 15),
        ("ipc", "price_close"),
        ("price_shift", 0),
    )

    def __init__(self):
        """Load the filter coefficients and set up the smoothing buffer."""
        self._coeffs = load_fn_coefficients(self.p.filter_number)
        self._price_line = resolve_price_line(self.data, self.p.ipc)
        self._smooth_values = deque(maxlen=max(1, int(self.p.xlength)))
        self.addminperiod(len(self._coeffs) + self.p.xlength + 5)

    def _smooth_filtered(self, value):
        self._smooth_values.append(value)
        values = list(self._smooth_values)
        if not values:
            return value
        mode = str(self.p.xma_method).lower()
        if mode in {"sma", "mode_sma"}:
            return sum(values) / len(values)
        if mode in {"ema", "mode_ema"}:
            alpha = 2.0 / (len(values) + 1.0)
            ema = values[0]
            for item in values[1:]:
                ema = alpha * item + (1.0 - alpha) * ema
            return ema
        weights = list(range(1, len(values) + 1))
        weight_sum = float(sum(weights))
        return sum(v * w for v, w in zip(values, weights)) / weight_sum

    def next(self):
        """Convolve the filter coefficients with price and emit the smoothed value."""
        filtered = 0.0
        for offset, coef in enumerate(self._coeffs):
            filtered += coef * float(self._price_line[-offset])
        self.lines.mafn[0] = self._smooth_filtered(filtered) + float(self.p.price_shift)
