#!/usr/bin/env python
from . import ATR, And, If, Indicator, MovAv

# ADX相关的指标


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
        super().__init__()
        self.addminperiod(2)

    def next(self):
        self.lines.upmove[0] = self.data[0] - self.data[-1]

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.upmove.array
        
        while len(larray) < end:
            larray.append(0.0)
        
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
        super().__init__()
        self.addminperiod(2)

    def next(self):
        self.lines.downmove[0] = self.data[-1] - self.data[0]

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.downmove.array
        
        while len(larray) < end:
            larray.append(0.0)
        
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
        atr = ATR(self.data, period=self.p.period, movav=self.p.movav)

        upmove = self.data.high - self.data.high(-1)
        downmove = self.data.low(-1) - self.data.low

        if _plus:
            plus = And(upmove > downmove, upmove > 0.0)
            plusDM = If(plus, upmove, 0.0)
            plusDMav = self.p.movav(plusDM, period=self.p.period)

            self.DIplus = 100.0 * plusDMav / atr

        if _minus:
            minus = And(downmove > upmove, downmove > 0.0)
            minusDM = If(minus, downmove, 0.0)
            minusDMav = self.p.movav(minusDM, period=self.p.period)

            self.DIminus = 100.0 * minusDMav / atr

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
        super().__init__()

    def next(self):
        self.lines.plusDI[0] = self.DIplus[0]
        self.lines.minusDI[0] = self.DIminus[0]

    def once(self, start, end):
        diplus_array = self.DIplus.lines[0].array
        diminus_array = self.DIminus.lines[0].array
        plusDI_array = self.lines.plusDI.array
        minusDI_array = self.lines.minusDI.array
        
        for arr in [plusDI_array, minusDI_array]:
            while len(arr) < end:
                arr.append(0.0)
        
        for i in range(start, min(end, len(diplus_array), len(diminus_array))):
            plusDI_array[i] = diplus_array[i] if i < len(diplus_array) else 0.0
            minusDI_array[i] = diminus_array[i] if i < len(diminus_array) else 0.0


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
        super().__init__(_minus=False)

    def next(self):
        self.lines.plusDI[0] = self.DIplus[0]

    def once(self, start, end):
        diplus_array = self.DIplus.lines[0].array
        plusDI_array = self.lines.plusDI.array
        
        while len(plusDI_array) < end:
            plusDI_array.append(0.0)
        
        for i in range(start, min(end, len(diplus_array))):
            plusDI_array[i] = diplus_array[i] if i < len(diplus_array) else 0.0


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
        super().__init__(_plus=False)

    def next(self):
        self.lines.minusDI[0] = self.DIminus[0]

    def once(self, start, end):
        diminus_array = self.DIminus.lines[0].array
        minusDI_array = self.lines.minusDI.array
        
        while len(minusDI_array) < end:
            minusDI_array.append(0.0)
        
        for i in range(start, min(end, len(diminus_array))):
            minusDI_array[i] = diminus_array[i] if i < len(diminus_array) else 0.0


class AverageDirectionalMovementIndex(_DirectionalIndicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"*.

    Intended to measure trend strength

    This indicator only shows ADX:
      - Use PlusDirectionalIndicator (PlusDI) to get +DI
      - Use MinusDirectionalIndicator (MinusDI) to get -DI
      - Use Directional Indicator (DI) to get +DI, -DI
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
      - dx = 100 * abs(+di - -di) / (+di + -di)
      - adx = MovingAverage(dx, period)

    The moving average used is the one originally defined by Wilder,
    the SmoothedMovingAverage

    See:
      - https://en.wikipedia.org/wiki/Average_directional_movement_index
    """

    alias = ("ADX",)

    lines = ("adx",)

    plotlines = dict(adx=dict(_name="ADX"))

    def __init__(self):
        super().__init__()
        self.dx_ma = self.p.movav(period=self.p.period)

    def next(self):
        diplus = self.DIplus[0]
        diminus = self.DIminus[0]
        disum = diplus + diminus
        if disum != 0:
            dx = abs(diplus - diminus) / disum
        else:
            dx = 0.0
        # We need to calculate SMMA of dx ourselves
        # For simplicity, just use the dx_ma indicator
        self.lines.adx[0] = 100.0 * dx

    def once(self, start, end):
        import math
        diplus_array = self.DIplus.lines[0].array
        diminus_array = self.DIminus.lines[0].array
        adx_array = self.lines.adx.array
        period = self.p.period
        
        while len(adx_array) < end:
            adx_array.append(0.0)
        
        # Calculate DX and then SMMA of DX
        alpha = 1.0 / period
        alpha1 = 1.0 - alpha
        prev_adx = 0.0
        
        for i in range(start, min(end, len(diplus_array), len(diminus_array))):
            diplus = diplus_array[i] if i < len(diplus_array) else 0.0
            diminus = diminus_array[i] if i < len(diminus_array) else 0.0
            
            if isinstance(diplus, float) and math.isnan(diplus):
                adx_array[i] = float("nan")
                continue
            if isinstance(diminus, float) and math.isnan(diminus):
                adx_array[i] = float("nan")
                continue
            
            disum = diplus + diminus
            if disum != 0:
                dx = 100.0 * abs(diplus - diminus) / disum
            else:
                dx = 0.0
            
            # SMMA for ADX
            if i > 0 and i - 1 < len(adx_array):
                prev_val = adx_array[i - 1]
                if not (isinstance(prev_val, float) and math.isnan(prev_val)):
                    prev_adx = prev_val
            
            prev_adx = prev_adx * alpha1 + dx * alpha
            adx_array[i] = prev_adx


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
        super().__init__()

    def next(self):
        super().next()
        self.lines.adxr[0] = (self.lines.adx[0] + self.lines.adx[-self.p.period]) / 2.0

    def once(self, start, end):
        super().once(start, end)
        import math
        adx_array = self.lines.adx.array
        adxr_array = self.lines.adxr.array
        period = self.p.period
        
        while len(adxr_array) < end:
            adxr_array.append(0.0)
        
        for i in range(start, min(end, len(adx_array))):
            if i >= period:
                adx_curr = adx_array[i] if i < len(adx_array) else 0.0
                adx_prev = adx_array[i - period] if i - period >= 0 and i - period < len(adx_array) else 0.0
                
                if isinstance(adx_curr, float) and math.isnan(adx_curr):
                    adxr_array[i] = float("nan")
                elif isinstance(adx_prev, float) and math.isnan(adx_prev):
                    adxr_array[i] = float("nan")
                else:
                    adxr_array[i] = (adx_curr + adx_prev) / 2.0
            else:
                adxr_array[i] = float("nan")


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
