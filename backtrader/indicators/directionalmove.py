#!/usr/bin/env python
"""Directional Movement Indicator Module - ADX and DI indicators.

This module provides the ADX (Average Directional Index) and
Directional Indicators developed by J. Welles Wilder, Jr. for
measuring trend strength.

Classes:
    UpMove: Upward move calculation.
    DownMove: Downward move calculation.
    _DirectionalIndicator: Base class for DI calculations.
    DirectionalIndicator: DI indicator (alias: DI).
    PlusDirectionalIndicator: +DI indicator (aliases: PlusDI, +DI).
    MinusDirectionalIndicator: -DI indicator (aliases: MinusDI, -DI).
    AverageDirectionalMovementIndex: ADX indicator (alias: ADX).
    AverageDirectionalMovementIndexRating: ADXR indicator (alias: ADXR).
    DirectionalMovementIndex: DMI with ADX and DI (alias: DMI).
    DirectionalMovement: Complete DM system (alias: DM).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            # Calculate ADX to measure trend strength
            self.adx = bt.indicators.ADX(self.data, period=14)

            # Or use DI for +DI and -DI
            self.di = bt.indicators.DI(self.data, period=14)

        def next(self):
            # Buy when trend is strong (ADX > 25) and +DI crosses above -DI
            if self.adx[0] > 25 and self.di.plusDI[0] > self.di.minusDI[0]:
                self.buy()
"""

from . import ATR, And, If, Indicator, MovAv
from ..lineroot import LineRoot
from ..functions import DivByZero


class UpMove(Indicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"* as part of the Directional Move System to
    calculate Directional Indicators.

    Positive if the given data has moved higher than the previous day

    Formula:
      - upmove = data - data(-1)

    See:
      - https://en.wikipedia.org/wiki/Average_directional_movement_index
    """

    lines = ("upmove",)

    def __init__(self):
        """Initialize the UpMove indicator.

        Sets minimum period to 2 for difference calculation.
        """
        super().__init__()
        self.addminperiod(2)

    def next(self):
        """Calculate up move for the current bar.

        Returns data - data(-1), the positive price change.
        """
        self.lines.upmove[0] = self.data[0] - self.data[-1]

    def once(self, start, end):
        """Calculate up moves in runonce mode.

        Computes data[i] - data[i-1] for each bar.
        """
        darray = self.data.array
        larray = self.lines.upmove.array

        while len(larray) < end:
            larray.append(float("nan"))

        for i in range(1, min(end, len(darray))):
            larray[i] = darray[i] - darray[i - 1]


class DownMove(Indicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"* as part of the Directional Move System to
    calculate Directional Indicators.

    Positive if the given data has moved lower than the previous day

    Formula:
      - downmove = data(-1) - data

    See:
      - https://en.wikipedia.org/wiki/Average_directional_movement_index
    """

    lines = ("downmove",)

    def __init__(self):
        """Initialize the DownMove indicator.

        Sets minimum period to 2 for difference calculation.
        """
        super().__init__()
        self.addminperiod(2)

    def next(self):
        """Calculate down move for the current bar.

        Returns data(-1) - data, the negative price change as positive value.
        """
        self.lines.downmove[0] = self.data[-1] - self.data[0]

    def once(self, start, end):
        """Calculate down moves in runonce mode.

        Computes data[i-1] - data[i] for each bar.
        """
        darray = self.data.array
        larray = self.lines.downmove.array

        while len(larray) < end:
            larray.append(float("nan"))

        for i in range(1, min(end, len(darray))):
            larray[i] = darray[i - 1] - darray[i]


class _DirectionalIndicator(Indicator):
    """
    This class serves as the root base class for all "Directional Movement
    System" related indicators, given that the calculations are first common
    and then derived from the common calculations.

    It can calculate the +DI and -DI values (using kwargs as the hint as to
    what to calculate) but doesn't assign them to lines. This is left for
    sublcases of this class.
    """

    params = (("period", 14), ("movav", MovAv.Smoothed))

    plotlines = dict(plusDI=dict(_name="+DI"), minusDI=dict(_name="-DI"))

    def _plotlabel(self):
        plabels = [self.p.period]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self, _plus=True, _minus=True):
        """Initialize the directional indicator base.

        Calculates +DI and -DI values based on directional movement.

        Args:
            _plus: Whether to calculate plus DI.
            _minus: Whether to calculate minus DI.
        """
        self._di_atr = ATR(self.data, period=self.p.period, movav=self.p.movav)

        upmove = self.data.high - self.data.high(-1)
        downmove = self.data.low(-1) - self.data.low

        if _plus:
            plus = And(upmove > downmove, upmove > 0.0)
            plusDM = If(plus, upmove, 0.0)
            self._plusDMav = self.p.movav(plusDM, period=self.p.period)

            self.DIplus = 100.0 * self._plusDMav / self._di_atr

        if _minus:
            minus = And(downmove > upmove, downmove > 0.0)
            minusDM = If(minus, downmove, 0.0)
            self._minusDMav = self.p.movav(minusDM, period=self.p.period)

            self.DIminus = 100.0 * self._minusDMav / self._di_atr

        super().__init__()


class DirectionalIndicator(_DirectionalIndicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"*.

    Intended to measure trend strength

    This indicator shows +DI, -DI:
      - Use PlusDirectionalIndicator (PlusDI) to get +DI
      - Use MinusDirectionalIndicator (MinusDI) to get -DI
      - Use AverageDirectionalIndex (ADX) to get ADX
      - Use AverageDirectionalIndexRating (ADXR) to get ADX, ADXR
      - Use DirectionalMovementIndex (DMI) to get ADX, +DI, -DI
      - Use DirectionalMovement (DM) to get ADX, ADXR, +DI, -DI

    Formula:
      - upmove = high - high(-1)
      - downmove = low(-1) - low
      - +dm = upmove if upmove > downmove and upmove > 0 else 0
      - -dm = downmove if downmove > upmove and downmove > 0 else 0
      - +di = 100 * MovingAverage(+dm, period) / atr(period)
      - -di = 100 * MovingAverage(-dm, period) / atr(period)

    The moving average used is the one originally defined by Wilder,
    the SmoothedMovingAverage

    See:
      - https://en.wikipedia.org/wiki/Average_directional_movement_index
    """

    alias = ("DI",)
    lines = (
        "plusDI",
        "minusDI",
    )

    def __init__(self):
        """Initialize the Directional Indicator.

        Calculates both +DI and -DI from raw OHLC using Wilder smoothing.
        """
        super().__init__()
        self.lines.plusDI = self.DIplus
        self.lines.minusDI = self.DIminus
        # State for Wilder smoothing (used by next/prenext)
        self._sm_tr = 0.0
        self._sm_pdm = 0.0
        self._sm_mdm = 0.0
        self._bar_count = 0

    def prenext(self):
        """Accumulate during warmup period."""
        self._di_accumulate()

    def nextstart(self):
        """Transition from warmup to live calculation."""
        self._di_accumulate()

    def next(self):
        """Calculate +DI and -DI for the current bar."""
        self._di_accumulate()

    def _di_accumulate(self):
        """Accumulate TR/DM and compute DI using Wilder smoothing."""
        period = self.p.period
        high = self.data.high[0]
        low = self.data.low[0]
        if len(self.data) <= 1:
            return
        try:
            prev_high = self.data.high[-1]
            prev_low = self.data.low[-1]
            prev_close = self.data.close[-1]
        except IndexError:
            return

        true_high = max(high, prev_close)
        true_low = min(low, prev_close)
        tr = true_high - true_low

        upmove = high - prev_high
        downmove = prev_low - low
        pdm = upmove if (upmove > downmove and upmove > 0) else 0.0
        mdm = downmove if (downmove > upmove and downmove > 0) else 0.0

        self._bar_count += 1

        if self._bar_count <= period:
            # Accumulate sums for seeding
            self._sm_tr += tr
            self._sm_pdm += pdm
            self._sm_mdm += mdm
        else:
            # Wilder smoothing: val = val - val/period + new
            self._sm_tr = self._sm_tr - self._sm_tr / period + tr
            self._sm_pdm = self._sm_pdm - self._sm_pdm / period + pdm
            self._sm_mdm = self._sm_mdm - self._sm_mdm / period + mdm

        if self._sm_tr > 0:
            self.lines.plusDI[0] = 100.0 * self._sm_pdm / self._sm_tr
            self.lines.minusDI[0] = 100.0 * self._sm_mdm / self._sm_tr
        else:
            self.lines.plusDI[0] = 0.0
            self.lines.minusDI[0] = 0.0

    def once(self, start, end):
        """Calculate DI values in runonce mode from raw OHLC."""
        period = self.p.period
        high_arr = self.data.high.array
        low_arr = self.data.low.array
        close_arr = self.data.close.array
        dst_plus = self.lines.plusDI.array
        dst_minus = self.lines.minusDI.array

        while len(dst_plus) < end:
            dst_plus.append(float('nan'))
        while len(dst_minus) < end:
            dst_minus.append(float('nan'))

        sm_tr = 0.0
        sm_pdm = 0.0
        sm_mdm = 0.0
        bar_count = 0

        for i in range(1, min(end, len(high_arr), len(low_arr), len(close_arr))):
            high = high_arr[i]
            low = low_arr[i]
            prev_high = high_arr[i - 1]
            prev_low = low_arr[i - 1]
            prev_close = close_arr[i - 1]

            true_high = max(high, prev_close)
            true_low = min(low, prev_close)
            tr = true_high - true_low

            upmove = high - prev_high
            downmove = prev_low - low
            pdm = upmove if (upmove > downmove and upmove > 0) else 0.0
            mdm = downmove if (downmove > upmove and downmove > 0) else 0.0

            bar_count += 1
            if bar_count <= period:
                sm_tr += tr
                sm_pdm += pdm
                sm_mdm += mdm
            else:
                sm_tr = sm_tr - sm_tr / period + tr
                sm_pdm = sm_pdm - sm_pdm / period + pdm
                sm_mdm = sm_mdm - sm_mdm / period + mdm

            if sm_tr > 0:
                dst_plus[i] = 100.0 * sm_pdm / sm_tr
                dst_minus[i] = 100.0 * sm_mdm / sm_tr
            else:
                dst_plus[i] = 0.0
                dst_minus[i] = 0.0

    prenext = LineRoot.prenext
    nextstart = LineRoot.nextstart
    next = LineRoot.next
    preonce = LineRoot.preonce
    oncestart = LineRoot.oncestart
    once = LineRoot.once


class PlusDirectionalIndicator(_DirectionalIndicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"*.

    Intended to measure trend strength

    This indicator shows +DI:
      - Use MinusDirectionalIndicator (MinusDI) to get -DI
      - Use Directional Indicator (DI) to get +DI, -DI
      - Use AverageDirectionalIndex (ADX) to get ADX
      - Use AverageDirectionalIndexRating (ADXR) to get ADX, ADXR
      - Use DirectionalMovementIndex (DMI) to get ADX, +DI, -DI
      - Use DirectionalMovement (DM) to get ADX, ADXR, +DI, -DI

    Formula:
      - upmove = high - high(-1)
      - downmove = low(-1) - low
      - +dm = upmove if upmove > downmove and upmove > 0 else 0
      - +di = 100 * MovingAverage(+dm, period) / atr(period)

    The moving average used is the one originally defined by Wilder,
    the SmoothedMovingAverage

    See:
      - https://en.wikipedia.org/wiki/Average_directional_movement_index
    """

    alias = (("PlusDI", "+DI"),)
    lines = ("plusDI",)

    plotinfo = dict(plotname="+DirectionalIndicator")

    def __init__(self):
        """Initialize the +DI indicator."""
        super().__init__(_minus=False)
        self.lines.plusDI = self.DIplus
        self._sm_tr = 0.0
        self._sm_pdm = 0.0
        self._bar_count = 0

    def _pdi_accumulate(self):
        period = self.p.period
        high = self.data.high[0]
        low = self.data.low[0]
        if len(self.data) <= 1:
            return
        try:
            prev_high = self.data.high[-1]
            prev_low = self.data.low[-1]
            prev_close = self.data.close[-1]
        except IndexError:
            return
        tr = max(high, prev_close) - min(low, prev_close)
        upmove = high - prev_high
        downmove = prev_low - low
        pdm = upmove if (upmove > downmove and upmove > 0) else 0.0
        self._bar_count += 1
        if self._bar_count <= period:
            self._sm_tr += tr
            self._sm_pdm += pdm
        else:
            self._sm_tr = self._sm_tr - self._sm_tr / period + tr
            self._sm_pdm = self._sm_pdm - self._sm_pdm / period + pdm
        self.lines.plusDI[0] = (100.0 * self._sm_pdm / self._sm_tr) if self._sm_tr > 0 else 0.0

    def prenext(self):
        self._pdi_accumulate()

    def nextstart(self):
        self._pdi_accumulate()

    def next(self):
        self._pdi_accumulate()

    def once(self, start, end):
        period = self.p.period
        high_arr = self.data.high.array
        low_arr = self.data.low.array
        close_arr = self.data.close.array
        dst = self.lines.plusDI.array
        while len(dst) < end:
            dst.append(float('nan'))
        sm_tr = 0.0
        sm_pdm = 0.0
        bc = 0
        for i in range(1, min(end, len(high_arr), len(low_arr), len(close_arr))):
            tr = max(high_arr[i], close_arr[i-1]) - min(low_arr[i], close_arr[i-1])
            upmove = high_arr[i] - high_arr[i-1]
            downmove = low_arr[i-1] - low_arr[i]
            pdm = upmove if (upmove > downmove and upmove > 0) else 0.0
            bc += 1
            if bc <= period:
                sm_tr += tr
                sm_pdm += pdm
            else:
                sm_tr = sm_tr - sm_tr / period + tr
                sm_pdm = sm_pdm - sm_pdm / period + pdm
            dst[i] = (100.0 * sm_pdm / sm_tr) if sm_tr > 0 else 0.0

    prenext = LineRoot.prenext
    nextstart = LineRoot.nextstart
    next = LineRoot.next
    preonce = LineRoot.preonce
    oncestart = LineRoot.oncestart
    once = LineRoot.once


class MinusDirectionalIndicator(_DirectionalIndicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"*.

    Intended to measure trend strength

    This indicator shows -DI:
      - Use PlusDirectionalIndicator (PlusDI) to get +DI
      - Use Directional Indicator (DI) to get +DI, -DI
      - Use AverageDirectionalIndex (ADX) to get ADX
      - Use AverageDirectionalIndexRating (ADXR) to get ADX, ADXR
      - Use DirectionalMovementIndex (DMI) to get ADX, +DI, -DI
      - Use DirectionalMovement (DM) to get ADX, ADXR, +DI, -DI

    Formula:
      - upmove = high - high(-1)
      - downmove = low(-1) - low
      - -dm = downmove if downmove > upmove and downmove > 0 else 0
      - -di = 100 * MovingAverage(-dm, period) / atr(period)

    The moving average used is the one originally defined by Wilder,
    the SmoothedMovingAverage

    See:
      - https://en.wikipedia.org/wiki/Average_directional_movement_index
    """

    alias = (("MinusDI", "-DI"),)
    lines = ("minusDI",)

    plotinfo = dict(plotname="-DirectionalIndicator")

    def __init__(self):
        """Initialize the -DI indicator."""
        super().__init__(_plus=False)
        self.lines.minusDI = self.DIminus
        self._sm_tr = 0.0
        self._sm_mdm = 0.0
        self._bar_count = 0

    def _mdi_accumulate(self):
        period = self.p.period
        high = self.data.high[0]
        low = self.data.low[0]
        if len(self.data) <= 1:
            return
        try:
            prev_high = self.data.high[-1]
            prev_low = self.data.low[-1]
            prev_close = self.data.close[-1]
        except IndexError:
            return
        tr = max(high, prev_close) - min(low, prev_close)
        upmove = high - prev_high
        downmove = prev_low - low
        mdm = downmove if (downmove > upmove and downmove > 0) else 0.0
        self._bar_count += 1
        if self._bar_count <= period:
            self._sm_tr += tr
            self._sm_mdm += mdm
        else:
            self._sm_tr = self._sm_tr - self._sm_tr / period + tr
            self._sm_mdm = self._sm_mdm - self._sm_mdm / period + mdm
        self.lines.minusDI[0] = (100.0 * self._sm_mdm / self._sm_tr) if self._sm_tr > 0 else 0.0

    def prenext(self):
        self._mdi_accumulate()

    def nextstart(self):
        self._mdi_accumulate()

    def next(self):
        self._mdi_accumulate()

    def once(self, start, end):
        period = self.p.period
        high_arr = self.data.high.array
        low_arr = self.data.low.array
        close_arr = self.data.close.array
        dst = self.lines.minusDI.array
        while len(dst) < end:
            dst.append(float('nan'))
        sm_tr = 0.0
        sm_mdm = 0.0
        bc = 0
        for i in range(1, min(end, len(high_arr), len(low_arr), len(close_arr))):
            tr = max(high_arr[i], close_arr[i-1]) - min(low_arr[i], close_arr[i-1])
            upmove = high_arr[i] - high_arr[i-1]
            downmove = low_arr[i-1] - low_arr[i]
            mdm = downmove if (downmove > upmove and downmove > 0) else 0.0
            bc += 1
            if bc <= period:
                sm_tr += tr
                sm_mdm += mdm
            else:
                sm_tr = sm_tr - sm_tr / period + tr
                sm_mdm = sm_mdm - sm_mdm / period + mdm
            dst[i] = (100.0 * sm_mdm / sm_tr) if sm_tr > 0 else 0.0

    prenext = LineRoot.prenext
    nextstart = LineRoot.nextstart
    next = LineRoot.next
    preonce = LineRoot.preonce
    oncestart = LineRoot.oncestart
    once = LineRoot.once


class AverageDirectionalMovementIndex(Indicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"*.

    Intended to measure trend strength. Rewritten following MACD pattern
    with explicit next()/once() methods for reliable calculation.

    Formula:
      - upmove = high - high(-1)
      - downmove = low(-1) - low
      - +dm = upmove if upmove > downmove and upmove > 0 else 0
      - -dm = downmove if downmove > upmove and downmove > 0 else 0
      - +di = 100 * MovingAverage(+dm, period) / atr(period)
      - -di = 100 * MovingAverage(-dm, period) / atr(period)
      - dx = 100 * abs(+di - -di) / (+di + -di)
      - adx = MovingAverage(dx, period)
    """

    alias = ("ADX",)
    lines = ("adx",)
    params = (("period", 14), ("movav", MovAv.Smoothed))
    plotlines = dict(adx=dict(_name="ADX"))

    def __init__(self):
        """Initialize the ADX indicator.

        Sets up ATR, DM smoothing, and state for ADX calculation.
        """
        super().__init__()
        period = self.p.period

        atr = ATR(self.data, period=period, movav=self.p.movav)
        upmove = self.data.high - self.data.high(-1)
        downmove = self.data.low(-1) - self.data.low

        plus = And(upmove > downmove, upmove > 0.0)
        plusDM = If(plus, upmove, 0.0)
        plusDMav = self.p.movav(plusDM, period=period)
        self.DIplus = 100.0 * plusDMav / atr

        minus = And(downmove > upmove, downmove > 0.0)
        minusDM = If(minus, downmove, 0.0)
        minusDMav = self.p.movav(minusDM, period=period)
        self.DIminus = 100.0 * minusDMav / atr

        dx = abs(self.DIplus - self.DIminus) / (self.DIplus + self.DIminus)
        self.lines.adx = 100.0 * self.p.movav(dx, period=period)

        # Store sub-indicators for direct array access (like MACD)
        self.atr = ATR(self.data, period=period, movav=self.p.movav)
        self.plusDMav = self.p.movav(period=period)
        self.minusDMav = self.p.movav(period=period)

        # Calculate minperiod: ATR needs period, then DI smoothing needs period, then ADX smoothing needs period
        # Total: approximately 2*period for DI + period for ADX smoothing
        adx_minperiod = 2 * period
        self._minperiod = max(self._minperiod, adx_minperiod)

        # Propagate minperiod to lines
        for line in self.lines:
            line.updateminperiod(self._minperiod)

        # For SMMA calculation
        self.alpha = 1.0 / period
        self.alpha1 = 1.0 - self.alpha

        # State for smoothed values
        self._plusDMav_val = 0.0
        self._minusDMav_val = 0.0
        self._adx_val = 0.0
        self._adx_bootstrapped = False
        self._last_adx_idx = None

    def prenext(self):
        """Track previous high/low during warmup.

        Stores high and low values for directional move calculation.
        """
        pass

    def _adx_atr_value(self, atr_array, index):
        import math

        atr_val = atr_array[index]
        if atr_val == 0 or (isinstance(atr_val, float) and math.isnan(atr_val)):
            return 0.0001
        return atr_val

    def _adx_dx(self, plus_dmav, minus_dmav, atr_val):
        diplus = 100.0 * plus_dmav / atr_val
        diminus = 100.0 * minus_dmav / atr_val
        disum = diplus + diminus
        return 100.0 * abs(diplus - diminus) / disum if disum != 0 else 0.0

    def _adx_bootstrap(self, target_idx):
        high_array = self.data.high.array
        low_array = self.data.low.array
        atr_array = self.atr.lines[0].array

        period = self.p.period
        seed_idx = 2 * period - 1
        data_len = min(len(high_array), len(low_array), len(atr_array))
        if target_idx < seed_idx or data_len <= seed_idx:
            return False

        dm_plus_sum = 0.0
        dm_minus_sum = 0.0
        for i in range(1, period + 1):
            upmove = high_array[i] - high_array[i - 1]
            downmove = low_array[i - 1] - low_array[i]
            dm_plus_sum += upmove if (upmove > downmove and upmove > 0) else 0.0
            dm_minus_sum += downmove if (downmove > upmove and downmove > 0) else 0.0

        plus_dmav = dm_plus_sum / period
        minus_dmav = dm_minus_sum / period
        dx_values = [
            self._adx_dx(plus_dmav, minus_dmav, self._adx_atr_value(atr_array, period))
        ]

        for i in range(period + 1, seed_idx + 1):
            upmove = high_array[i] - high_array[i - 1]
            downmove = low_array[i - 1] - low_array[i]
            plus_dm = upmove if (upmove > downmove and upmove > 0) else 0.0
            minus_dm = downmove if (downmove > upmove and downmove > 0) else 0.0
            plus_dmav = plus_dmav * self.alpha1 + plus_dm * self.alpha
            minus_dmav = minus_dmav * self.alpha1 + minus_dm * self.alpha
            dx_values.append(
                self._adx_dx(plus_dmav, minus_dmav, self._adx_atr_value(atr_array, i))
            )

        self._plusDMav_val = plus_dmav
        self._minusDMav_val = minus_dmav
        self._adx_val = sum(dx_values[:period]) / period
        self._last_adx_idx = seed_idx
        self._adx_bootstrapped = True
        return True

    def _adx_advance_to(self, target_idx):
        if not self._adx_bootstrapped and not self._adx_bootstrap(target_idx):
            return False

        high_array = self.data.high.array
        low_array = self.data.low.array
        atr_array = self.atr.lines[0].array
        data_len = min(len(high_array), len(low_array), len(atr_array))
        if target_idx >= data_len:
            return False

        for i in range(self._last_adx_idx + 1, target_idx + 1):
            upmove = high_array[i] - high_array[i - 1]
            downmove = low_array[i - 1] - low_array[i]
            plus_dm = upmove if (upmove > downmove and upmove > 0) else 0.0
            minus_dm = downmove if (downmove > upmove and downmove > 0) else 0.0
            self._plusDMav_val = self._plusDMav_val * self.alpha1 + plus_dm * self.alpha
            self._minusDMav_val = self._minusDMav_val * self.alpha1 + minus_dm * self.alpha
            dx = self._adx_dx(
                self._plusDMav_val,
                self._minusDMav_val,
                self._adx_atr_value(atr_array, i),
            )
            self._adx_val = self._adx_val * self.alpha1 + dx * self.alpha
            self._last_adx_idx = i

        return True

    def nextstart(self):
        """Seed ADX calculation on first valid bar.

        Calculates initial DM, DI, DX, and ADX values.
        """
        idx = self.lines[0].idx
        if self._adx_advance_to(idx):
            self.lines.adx[0] = self._adx_val
        else:
            self.lines.adx[0] = float("nan")

    def next(self):
        """Calculate ADX for the current bar.

        Calculates DM smoothing, DI, DX, and ADX values.
        """
        idx = self.lines[0].idx
        if self._adx_advance_to(idx):
            self.lines.adx[0] = self._adx_val
        else:
            self.lines.adx[0] = float("nan")

    def once(self, start, end):
        """Calculate ADX in runonce mode using proper Wilder seeding.

        Implements the standard Wilder ADX algorithm:
        Phase 1: Seed smoothed DM with SMA of first N DM values (bars 1..period)
        Phase 2: Continue SMMA for DM, accumulate DX (bars period..2*period-1)
        Phase 3: Seed ADX with SMA of first N DX values
        Phase 4: Continue SMMA for all components (bars 2*period..end)
        """
        import math

        # Get source arrays
        high_array = self.data.high.array
        low_array = self.data.low.array
        atr_array = self.atr.lines[0].array
        adx_array = self.lines.adx.array

        period = self.p.period
        alpha = self.alpha
        alpha1 = self.alpha1

        # Ensure arrays are sized
        while len(adx_array) < end:
            adx_array.append(float("nan"))

        data_len = min(end, len(high_array), len(low_array), len(atr_array))

        # Pre-fill warmup with NaN
        for i in range(min(2 * period, data_len)):
            adx_array[i] = float("nan")

        # Need at least 2*period + 1 bars for proper seeding
        if data_len <= 2 * period:
            return

        # Phase 1: Calculate raw DM values for bars 1..period
        # Seed smoothed DM with SMA (average) of first period values
        dm_plus_sum = 0.0
        dm_minus_sum = 0.0

        for i in range(1, period + 1):
            upmove = high_array[i] - high_array[i - 1]
            downmove = low_array[i - 1] - low_array[i]
            plusDM = upmove if (upmove > downmove and upmove > 0) else 0.0
            minusDM = downmove if (downmove > upmove and downmove > 0) else 0.0
            dm_plus_sum += plusDM
            dm_minus_sum += minusDM

        plusDMav = dm_plus_sum / period
        minusDMav = dm_minus_sum / period

        # Phase 2: Calculate DI and DX for bars period..2*period-1
        # Continue SMMA for DM, accumulate DX values for ADX seeding
        dx_list = []

        # First DX at bar period (using seeded DM averages)
        atr_val = atr_array[period]
        if atr_val == 0 or (isinstance(atr_val, float) and math.isnan(atr_val)):
            atr_val = 0.0001
        diplus = 100.0 * plusDMav / atr_val
        diminus = 100.0 * minusDMav / atr_val
        disum = diplus + diminus
        dx = 100.0 * abs(diplus - diminus) / disum if disum != 0 else 0.0
        dx_list.append(dx)

        # Continue for bars period+1 to 2*period-1
        for i in range(period + 1, 2 * period):
            upmove = high_array[i] - high_array[i - 1]
            downmove = low_array[i - 1] - low_array[i]
            plusDM = upmove if (upmove > downmove and upmove > 0) else 0.0
            minusDM = downmove if (downmove > upmove and downmove > 0) else 0.0

            plusDMav = plusDMav * alpha1 + plusDM * alpha
            minusDMav = minusDMav * alpha1 + minusDM * alpha

            atr_val = atr_array[i]
            if atr_val == 0 or (isinstance(atr_val, float) and math.isnan(atr_val)):
                atr_val = 0.0001

            diplus = 100.0 * plusDMav / atr_val
            diminus = 100.0 * minusDMav / atr_val
            disum = diplus + diminus
            dx = 100.0 * abs(diplus - diminus) / disum if disum != 0 else 0.0
            dx_list.append(dx)

        # Phase 3: Seed ADX with SMA of first period DX values
        adx_val = sum(dx_list[:period]) / period
        adx_array[2 * period - 1] = adx_val

        # Phase 4: Continue SMMA for everything from 2*period onwards
        for i in range(2 * period, data_len):
            upmove = high_array[i] - high_array[i - 1]
            downmove = low_array[i - 1] - low_array[i]
            plusDM = upmove if (upmove > downmove and upmove > 0) else 0.0
            minusDM = downmove if (downmove > upmove and downmove > 0) else 0.0

            plusDMav = plusDMav * alpha1 + plusDM * alpha
            minusDMav = minusDMav * alpha1 + minusDM * alpha

            atr_val = atr_array[i]
            if atr_val == 0 or (isinstance(atr_val, float) and math.isnan(atr_val)):
                atr_val = 0.0001

            diplus = 100.0 * plusDMav / atr_val
            diminus = 100.0 * minusDMav / atr_val
            disum = diplus + diminus
            dx = 100.0 * abs(diplus - diminus) / disum if disum != 0 else 0.0

            adx_val = adx_val * alpha1 + dx * alpha
            adx_array[i] = adx_val

    prenext = LineRoot.prenext
    nextstart = LineRoot.nextstart
    next = LineRoot.next
    preonce = LineRoot.preonce
    oncestart = LineRoot.oncestart
    once = LineRoot.once


class AverageDirectionalMovementIndexRating(AverageDirectionalMovementIndex):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"*.

    Intended to measure trend strength.

    ADXR is the average of ADX with a value period bars ago

    This indicator shows the ADX and ADXR:
      - Use PlusDirectionalIndicator (PlusDI) to get +DI
      - Use MinusDirectionalIndicator (MinusDI) to get -DI
      - Use Directional Indicator (DI) to get +DI, -DI
      - Use AverageDirectionalIndex (ADX) to get ADX
      - Use DirectionalMovementIndex (DMI) to get ADX, +DI, -DI
      - Use DirectionalMovement (DM) to get ADX, ADXR, +DI, -DI

    Formula:
      - upmove = high - high(-1)
      - downmove = low(-1) - low
      - +dm = upmove if upmove > downmove and upmove > 0 else 0
      - -dm = downmove if downmove > upmove and downmove > 0 else 0
      - +di = 100 * MovingAverage(+dm, period) / atr(period)
      - -di = 100 * MovingAverage(-dm, period) / atr(period)
      - dx = 100 * abs(+di - -di) / (+di + -di)
      - adx = MovingAverage(dx, period)
      - adxr = (adx + adx(-period)) / 2

    The moving average used is the one originally defined by Wilder,
    the SmoothedMovingAverage

    See:
      - https://en.wikipedia.org/wiki/Average_directional_movement_index
    """

    alias = ("ADXR",)

    lines = ("adxr",)
    plotlines = dict(adxr=dict(_name="ADXR"))

    def __init__(self):
        """Initialize the ADXR indicator.

        Extends ADX with rating line.
        """
        super().__init__()
        self.lines.adxr = (self.l.adx + self.l.adx(-self.p.period)) / 2.0

    def next(self):
        """Calculate ADX and ADXR for the current bar.

        ADXR = (ADX + ADX(-period)) / 2
        """
        super().next()
        self.lines.adxr[0] = (self.lines.adx[0] + self.lines.adx[-self.p.period]) / 2.0

    def once(self, start, end):
        """Calculate ADXR in runonce mode.

        Computes ADXR as average of current ADX and ADX from period ago.
        """
        super().once(start, end)
        import math

        adx_array = self.lines.adx.array
        adxr_array = self.lines.adxr.array
        period = self.p.period

        while len(adxr_array) < end:
            adxr_array.append(float("nan"))

        for i in range(start, min(end, len(adx_array))):
            if i >= period:
                adx_curr = adx_array[i] if i < len(adx_array) else 0.0
                adx_prev = (
                    adx_array[i - period]
                    if i - period >= 0 and i - period < len(adx_array)
                    else 0.0
                )

                if isinstance(adx_curr, float) and math.isnan(adx_curr):
                    adxr_array[i] = float("nan")
                elif isinstance(adx_prev, float) and math.isnan(adx_prev):
                    adxr_array[i] = float("nan")
                else:
                    adxr_array[i] = (adx_curr + adx_prev) / 2.0
            else:
                adxr_array[i] = float("nan")

    prenext = LineRoot.prenext
    nextstart = LineRoot.nextstart
    next = LineRoot.next
    preonce = LineRoot.preonce
    oncestart = LineRoot.oncestart
    once = LineRoot.once


class DirectionalMovementIndex(AverageDirectionalMovementIndex, DirectionalIndicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"*.

    Intended to measure trend strength

    This indicator shows the ADX, +DI, -DI:
      - Use PlusDirectionalIndicator (PlusDI) to get +DI
      - Use MinusDirectionalIndicator (MinusDI) to get -DI
      - Use Directional Indicator (DI) to get +DI, -DI
      - Use AverageDirectionalIndex (ADX) to get ADX
      - Use AverageDirectionalIndexRating (ADXRating) to get ADX, ADXR
      - Use DirectionalMovement (DM) to get ADX, ADXR, +DI, -DI

    Formula:
      - upmove = high - high(-1)
      - downmove = low(-1) - low
      - +dm = upmove if upmove > downmove and upmove > 0 else 0
      - -dm = downmove if downmove > upmove and downmove > 0 else 0
      - +di = 100 * MovingAverage(+dm, period) / atr(period)
      - -di = 100 * MovingAverage(-dm, period) / atr(period)
      - dx = 100 * abs(+di - -di) / (+di + -di)
      - adx = MovingAverage(dx, period)

    The moving average used is the one originally defined by Wilder,
    the SmoothedMovingAverage

    See:
      - https://en.wikipedia.org/wiki/Average_directional_movement_index
    """

    alias = ("DMI",)


class DirectionalMovement(AverageDirectionalMovementIndexRating, DirectionalIndicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"*.

    Intended to measure trend strength

    This indicator shows ADX, ADXR, +DI, -DI.

      - Use PlusDirectionalIndicator (PlusDI) to get +DI
      - Use MinusDirectionalIndicator (MinusDI) to get -DI
      - Use Directional Indicator (DI) to get +DI, -DI
      - Use AverageDirectionalIndex (ADX) to get ADX
      - Use AverageDirectionalIndexRating (ADXR) to get ADX, ADXR
      - Use DirectionalMovementIndex (DMI) to get ADX, +DI, -DI

    Formula:
      - upmove = high - high(-1)
      - downmove = low(-1) - low
      - +dm = upmove if upmove > downmove and upmove > 0 else 0
      - -dm = downmove if downmove > upmove and downmove > 0 else 0
      - +di = 100 * MovingAverage(+dm, period) / atr(period)
      - -di = 100 * MovingAverage(-dm, period) / atr(period)
      - dx = 100 * abs(+di - -di) / (+di + -di)
      - adx = MovingAverage(dx, period)

    The moving average used is the one originally defined by Wilder,
    the SmoothedMovingAverage

    See:
      - https://en.wikipedia.org/wiki/Average_directional_movement_index
    """

    alias = ("DM",)
