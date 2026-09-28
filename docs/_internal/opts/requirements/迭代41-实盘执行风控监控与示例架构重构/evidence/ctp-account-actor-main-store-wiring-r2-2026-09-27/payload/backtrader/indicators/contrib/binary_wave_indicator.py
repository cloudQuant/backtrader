#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    CCI,
    EMA,
    MACD,
    RSI,
    SMA,
    Indicator,
    MinusDirectionalIndicator,
    PlusDirectionalIndicator,
)

__all__ = [
    "BinaryWaveIndicator",
]


class BinaryWaveIndicator(Indicator):
    """Weighted indicator that builds a smoothed wave signal from multiple sub-indicators."""

    lines = (
        "wave",
        "raw",
    )
    params = (
        ("weight_ma", 1.0),
        ("weight_macd", 1.0),
        ("weight_osma", 1.0),
        ("weight_cci", 1.0),
        ("weight_mom", 1.0),
        ("weight_rsi", 1.0),
        ("weight_adx", 1.0),
        ("ma_period", 13),
        ("ma_type", "ema"),
        ("fast_macd", 12),
        ("slow_macd", 26),
        ("signal_macd", 9),
        ("cci_period", 14),
        ("mom_period", 14),
        ("rsi_period", 14),
        ("adx_period", 14),
        ("smooth_period", 5),
    )

    def __init__(self):
        """Instantiate sub-indicators and configure required minimum periods."""
        ma_type = str(self.p.ma_type).lower()
        ma_cls = EMA if ma_type == "ema" else SMA
        self.ma = ma_cls(self.data.close, period=self.p.ma_period)
        self.macd = MACD(
            self.data.close,
            period_me1=self.p.fast_macd,
            period_me2=self.p.slow_macd,
            period_signal=self.p.signal_macd,
        )
        self.cci = CCI(self.data, period=self.p.cci_period)
        self.rsi = RSI(self.data.close, period=self.p.rsi_period)
        self.plus_di = PlusDirectionalIndicator(self.data, period=self.p.adx_period)
        self.minus_di = MinusDirectionalIndicator(self.data, period=self.p.adx_period)
        self.addminperiod(
            max(
                self.p.ma_period,
                self.p.slow_macd + self.p.signal_macd,
                self.p.cci_period,
                self.p.mom_period + 1,
                self.p.rsi_period,
                self.p.adx_period,
                self.p.smooth_period,
            )
            + 5
        )

    def _momentum_ratio(self, idx=0):
        base_idx = idx - self.p.mom_period
        base = float(self.data.close[base_idx])
        if base == 0:
            return 100.0
        return float(self.data.close[idx]) / base * 100.0

    def _score(self):
        score = 0.0
        if self.p.weight_ma > 0:
            if float(self.data.close[0]) > float(self.ma[0]):
                score += self.p.weight_ma
            elif float(self.data.close[0]) < float(self.ma[0]):
                score -= self.p.weight_ma
        if self.p.weight_macd > 0:
            macd_now = float(self.macd.macd[0])
            macd_prev = float(self.macd.macd[-1])
            if macd_now > macd_prev:
                score += self.p.weight_macd
            elif macd_now < macd_prev:
                score -= self.p.weight_macd
        if self.p.weight_osma > 0:
            osma = float(self.macd.macd[0] - self.macd.signal[0])
            if osma > 0:
                score += self.p.weight_osma
            elif osma < 0:
                score -= self.p.weight_osma
        if self.p.weight_cci > 0:
            cci = float(self.cci[0])
            if cci > 0:
                score += self.p.weight_cci
            elif cci < 0:
                score -= self.p.weight_cci
        if self.p.weight_mom > 0:
            mom = self._momentum_ratio(0)
            if mom > 100.0:
                score += self.p.weight_mom
            elif mom < 100.0:
                score -= self.p.weight_mom
        if self.p.weight_rsi > 0:
            rsi = float(self.rsi[0])
            if rsi > 50.0:
                score += self.p.weight_rsi
            elif rsi < 50.0:
                score -= self.p.weight_rsi
        if self.p.weight_adx > 0:
            plus_di = float(self.plus_di[0])
            minus_di = float(self.minus_di[0])
            if plus_di > minus_di:
                score += self.p.weight_adx
            elif plus_di < minus_di:
                score -= self.p.weight_adx
        return score

    def next(self):
        """Update raw and smoothed wave values for a single bar."""
        raw = self._score()
        self.lines.raw[0] = raw
        if len(self) == 1:
            self.lines.wave[0] = raw
            return
        alpha = 2.0 / (self.p.smooth_period + 1.0)
        prev_wave = float(self.lines.wave[-1])
        if prev_wave != prev_wave:
            prev_wave = raw
        self.lines.wave[0] = prev_wave + alpha * (raw - prev_wave)

    def once(self, start, end):
        """Calculate raw and smoothed wave arrays for a range of bars.

        Args:
            start: Start index for batch evaluation.
            end: End index (exclusive) for batch evaluation.
        """
        close_array = self.data.close.array
        ma_array = self.ma.array
        macd_array = self.macd.macd.array
        macd_signal_array = self.macd.signal.array
        cci_array = self.cci.array
        rsi_array = self.rsi.array
        plus_di_array = self.plus_di.array
        minus_di_array = self.minus_di.array
        wave_line = self.lines.wave.array
        raw_line = self.lines.raw.array
        for line in (wave_line, raw_line):
            while len(line) < end:
                line.append(float("nan"))

        alpha = 2.0 / (self.p.smooth_period + 1.0)
        prev_wave = None
        actual_end = min(
            end,
            len(close_array),
            len(ma_array),
            len(macd_array),
            len(macd_signal_array),
            len(cci_array),
            len(rsi_array),
            len(plus_di_array),
            len(minus_di_array),
        )
        for i in range(start, actual_end):
            score = 0.0
            close = float(close_array[i])
            if self.p.weight_ma > 0:
                ma = float(ma_array[i])
                if close > ma:
                    score += self.p.weight_ma
                elif close < ma:
                    score -= self.p.weight_ma
            if self.p.weight_macd > 0 and i > 0:
                macd_now = float(macd_array[i])
                macd_prev = float(macd_array[i - 1])
                if macd_now > macd_prev:
                    score += self.p.weight_macd
                elif macd_now < macd_prev:
                    score -= self.p.weight_macd
            if self.p.weight_osma > 0:
                osma = float(macd_array[i]) - float(macd_signal_array[i])
                if osma > 0:
                    score += self.p.weight_osma
                elif osma < 0:
                    score -= self.p.weight_osma
            if self.p.weight_cci > 0:
                cci = float(cci_array[i])
                if cci > 0:
                    score += self.p.weight_cci
                elif cci < 0:
                    score -= self.p.weight_cci
            if self.p.weight_mom > 0:
                base_idx = i - int(self.p.mom_period)
                base = float(close_array[base_idx]) if base_idx >= 0 else 0.0
                mom = close / base * 100.0 if base else 100.0
                if mom > 100.0:
                    score += self.p.weight_mom
                elif mom < 100.0:
                    score -= self.p.weight_mom
            if self.p.weight_rsi > 0:
                rsi = float(rsi_array[i])
                if rsi > 50.0:
                    score += self.p.weight_rsi
                elif rsi < 50.0:
                    score -= self.p.weight_rsi
            if self.p.weight_adx > 0:
                plus_di = float(plus_di_array[i])
                minus_di = float(minus_di_array[i])
                if plus_di > minus_di:
                    score += self.p.weight_adx
                elif plus_di < minus_di:
                    score -= self.p.weight_adx

            raw_line[i] = score
            wave = score if prev_wave is None else prev_wave + alpha * (score - prev_wave)
            wave_line[i] = wave
            prev_wave = wave
