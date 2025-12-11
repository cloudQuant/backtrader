#!/usr/bin/env python


from ..indicators import PeriodN

__all__ = ["Fractal"]


class Fractal(PeriodN):
    """
    References:
        [Ref 1] http://www.investopedia.com/articles/trading/06/fractals.asp

    """

    lines = ("fractal_bearish", "fractal_bullish")

    plotinfo = dict(subplot=False, plotlinelabels=False, plot=True)

    plotlines = dict(
        fractal_bearish=dict(
            marker="^", markersize=4.0, color="lightblue", fillstyle="full", ls=""
        ),
        fractal_bullish=dict(
            marker="v", markersize=4.0, color="lightblue", fillstyle="full", ls=""
        ),
    )
    params = (
        ("period", 5),
        ("bardist", 0.015),  # distance to max/min in absolute perc
        ("shift_to_potential_fractal", 2),
    )

    def next(self):
        # A bearish turning point occurs when there is a pattern with the
        # highest high in the middle and two lower highs on each side. [Ref 1]

        last_five_highs = self.data.high.get(size=self.p.period)
        max_val = max(last_five_highs)
        max_idx = last_five_highs.index(max_val)

        if max_idx == self.p.shift_to_potential_fractal:
            self.lines.fractal_bearish[-2] = max_val * (1 + self.p.bardist)

        # A bullish turning point occurs when there is a pattern with the
        # lowest low in the middle and two higher lowers on each side. [Ref 1]
        last_five_lows = self.data.low.get(size=self.p.period)
        min_val = min(last_five_lows)
        min_idx = last_five_lows.index(min_val)

        if min_idx == self.p.shift_to_potential_fractal:
            self.l.fractal_bullish[-2] = min_val * (1 - self.p.bardist)
