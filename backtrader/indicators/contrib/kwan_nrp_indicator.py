#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    RSI,
    Indicator,
    MomentumOscillator,
    Stochastic,
)

__all__ = [
    "KwanNrpIndicator",
]


class KwanNrpIndicator(Indicator):
    """Compute smoothed KWAN_NRP value and direction direction states."""

    lines = (
        "kwan",
        "direction",
    )

    params = (
        ("k_period", 5),
        ("d_period", 3),
        ("slowing", 3),
        ("rsi_period", 14),
        ("momentum_period", 14),
        ("x_length", 3),
    )

    def __init__(self):
        """Prepare stochastic, RSI, and momentum components for indicator output."""
        # --- Stochastic %D (signal line) ---
        stoch = Stochastic(
            self.data,
            period=self.p.k_period,
            period_dfast=self.p.slowing,
            period_dslow=self.p.d_period,
        )
        self.stoch_d = stoch.percD

        # --- RSI ---
        self.rsi = RSI(
            self.data.close,
            period=self.p.rsi_period,
        )

        # --- Momentum Oscillator  = 100 * close / close[-period] ---
        self.mom_osc = MomentumOscillator(
            self.data.close,
            period=self.p.momentum_period,
        )

        # --- Raw KWAN oscillator ---
        # kwan_raw = stoch_d * rsi / mom_osc
        # Guard against mom_osc == 0 in next() and protect period alignment.
        self.addminperiod(
            max(
                self.p.k_period + self.p.slowing + self.p.d_period,
                self.p.rsi_period,
                self.p.momentum_period,
            )
            + self.p.x_length
            + 2
        )

        # Internal raw value buffer.
        self._raw_buf = []

    def next(self):
        """Update KWAN value and directional signal line."""
        mom = self.mom_osc[0]
        if mom == 0 or not math.isfinite(mom):
            kwan_raw = 100.0
        else:
            kwan_raw = self.stoch_d[0] * self.rsi[0] / mom

        self._raw_buf.append(kwan_raw)

        # Smooth raw values with a simple moving average of the last XLength bars.
        xl = self.p.x_length
        if len(self._raw_buf) >= xl:
            smoothed = sum(self._raw_buf[-xl:]) / xl
        else:
            smoothed = kwan_raw

        self.lines.kwan[0] = smoothed

        # Determine direction: rise / fall / flat versus previous smoothed value.
        if len(self._raw_buf) < xl + 1:
            self.lines.direction[0] = 1.0
            return

        prev_smoothed_vals = self._raw_buf[-(xl + 1) : -1]
        if len(prev_smoothed_vals) >= xl:
            prev_smoothed = sum(prev_smoothed_vals[-xl:]) / xl
        else:
            prev_smoothed = smoothed

        if smoothed > prev_smoothed:
            self.lines.direction[0] = 0.0  # rising
        elif smoothed < prev_smoothed:
            self.lines.direction[0] = 2.0  # falling
        else:
            self.lines.direction[0] = 1.0
