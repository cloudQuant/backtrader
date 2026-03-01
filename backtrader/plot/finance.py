#!/usr/bin/env python
"""Financial plotting utilities for backtrader.

This module provides plot handlers and functions for rendering various
financial chart types including candlestick, OHLC, volume, and line-on-close
plots using matplotlib.
"""

import matplotlib.collections as mcol
import matplotlib.colors as mcolors
import matplotlib.legend as mlegend
import matplotlib.lines as mlines

from ..utils.py3 import range, zip
from .utils import shade_color


class CandlestickPlotHandler:
    """Handler for creating and managing candlestick plot collections.

    This class creates matplotlib collections for rendering candlestick charts
    with customizable colors for up and down bars. It also provides custom
    legend rendering for candlestick patterns.

    Attributes:
        legend_opens: Open prices for legend sample candles.
        legend_highs: High prices for legend sample candles.
        legend_lows: Low prices for legend sample candles.
        legend_closes: Close prices for legend sample candles.
        colorup: RGBA color for up bars (close > open).
        colordown: RGBA color for down bars (close < open).
        edgeup: RGBA edge color for up bars.
        edgedown: RGBA edge color for down bars.
        tickup: RGBA color for up tick marks.
        tickdown: RGBA color for down tick marks.
        barcol: PolyCollection containing the candlestick bodies.
        tickcol: LineCollection containing the candlestick wicks.
    """

    legend_opens = [0.50, 0.50, 0.50]
    legend_highs = [1.00, 1.00, 1.00]
    legend_lows = [0.00, 0.00, 0.00]
    legend_closes = [0.80, 0.00, 1.00]

    def __init__(
        self,
        ax,
        x,
        opens,
        highs,
        lows,
        closes,
        colorup="k",
        colordown="r",
        edgeup=None,
        edgedown=None,
        tickup=None,
        tickdown=None,
        width=1,
        tickwidth=1,
        edgeadjust=0.05,
        edgeshading=-10,
        alpha=1.0,
        label="_nolegend",
        fillup=True,
        filldown=True,
        **kwargs,
    ):
        """Initialize the candlestick plot handler.

        Args:
            ax: Matplotlib axes object to add collections to.
            x: Array of x-axis coordinates (typically bar indices).
            opens: Array of opening prices.
            highs: Array of high prices.
            lows: Array of low prices.
            closes: Array of closing prices.
            colorup: Color for up bars (close > open). Default is "k" (black).
            colordown: Color for down bars (close < open). Default is "r" (red).
            edgeup: Edge color for up bars. If None, derived from colorup with shading.
            edgedown: Edge color for down bars. If None, derived from colordown with shading.
            tickup: Color for up tick marks (wicks). If None, uses edgeup.
            tickdown: Color for down tick marks (wicks). If None, uses edgedown.
            width: Width of candlestick bodies. Default is 1.
            tickwidth: Width of candlestick wicks. Default is 1.
            edgeadjust: Adjustment for edge width. Default is 0.05.
            edgeshading: Shading factor for edge colors. Default is -10.
            alpha: Transparency level (0-1). Default is 1.0.
            label: Label for legend. Default is "_nolegend".
            fillup: Whether to fill up bars. Default is True.
            filldown: Whether to fill down bars. Default is True.
            **kwargs: Additional keyword arguments passed to collections.

        Raises:
            ValueError: If color conversion fails.
        """
        # Manager up/down bar colors
        r, g, b = mcolors.colorConverter.to_rgb(colorup)
        self.colorup = r, g, b, alpha
        r, g, b = mcolors.colorConverter.to_rgb(colordown)
        self.colordown = r, g, b, alpha
        # Manage the edge up/down colors for the bars
        if edgeup:
            r, g, b = mcolors.colorConverter.to_rgb(edgeup)
            self.edgeup = ((r, g, b, alpha),)
        else:
            self.edgeup = shade_color(self.colorup, edgeshading)

        if edgedown:
            r, g, b = mcolors.colorConverter.to_rgb(edgedown)
            self.edgedown = ((r, g, b, alpha),)
        else:
            self.edgedown = shade_color(self.colordown, edgeshading)

            # Manage the up/down tick colors
        if tickup:
            r, g, b = mcolors.colorConverter.to_rgb(tickup)
            self.tickup = ((r, g, b, alpha),)
        else:
            self.tickup = self.edgeup

        if tickdown:
            r, g, b = mcolors.colorConverter.to_rgb(tickdown)
            self.tickdown = ((r, g, b, alpha),)
        else:
            self.tickdown = self.edgedown

        self.barcol, self.tickcol = self.barcollection(
            x,
            opens,
            highs,
            lows,
            closes,
            width,
            tickwidth,
            edgeadjust,
            label=label,
            fillup=fillup,
            filldown=filldown,
            **kwargs,
        )

        # add collections to the axis and return them
        ax.add_collection(self.tickcol)
        ax.add_collection(self.barcol)

        # Update the axis
        ax.update_datalim(((0, min(lows)), (len(opens), max(highs))))
        ax.autoscale_view()

        # Add self as legend handler for this object
        mlegend.Legend.update_default_handler_map({self.barcol: self})

    def legend_artist(self, legend, orig_handle, fontsize, handlebox):
        """Create a custom legend artist for candlestick plots.

        Args:
            legend: The legend object being created.
            orig_handle: The original handle for which the artist is created.
            fontsize: The font size for the legend.
            handlebox: The handlebox container for positioning the legend artist.

        Returns:
            Tuple of (barcol, tickcol): The bar and tick collections for the legend.
        """
        x0 = handlebox.xdescent
        y0 = handlebox.ydescent
        width = handlebox.width / len(self.legend_opens)
        height = handlebox.height

        # Generate the x-axis coordinates (handlebox based)
        xs = [x0 + width * (i + 0.5) for i in range(len(self.legend_opens))]

        barcol, tickcol = self.barcollection(
            xs,
            self.legend_opens,
            self.legend_highs,
            self.legend_lows,
            self.legend_closes,
            width=width,
            tickwidth=2,
            scaling=height,
            bot=y0,
        )

        barcol.set_transform(handlebox.get_transform())
        handlebox.add_artist(barcol)
        tickcol.set_transform(handlebox.get_transform())
        handlebox.add_artist(tickcol)

        return barcol, tickcol

    def barcollection(
        self,
        xs,
        opens,
        highs,
        lows,
        closes,
        width,
        tickwidth=1,
        edgeadjust=0,
        label="_nolegend",
        scaling=1.0,
        bot=0,
        fillup=True,
        filldown=True,
        **kwargs,
    ):
        """Create matplotlib collections for candlestick bars and wicks.

        Args:
            xs: Array of x-axis coordinates.
            opens: Array of opening prices.
            highs: Array of high prices.
            lows: Array of low prices.
            closes: Array of closing prices.
            width: Width of candlestick bodies.
            tickwidth: Width of candlestick wicks. Default is 1.
            edgeadjust: Adjustment for edge width. Default is 0.
            label: Label for legend. Default is "_nolegend".
            scaling: Vertical scaling factor. Default is 1.0.
            bot: Bottom offset for vertical positioning. Default is 0.
            fillup: Whether to fill up bars. Default is True.
            filldown: Whether to fill down bars. Default is True.
            **kwargs: Additional keyword arguments passed to collections.

        Returns:
            Tuple of (barcol, tickcol): PolyCollection for bodies and LineCollection for wicks.
        """
        # Prepack different zips of the series values
        oc = lambda: zip(opens, closes)  # NOQA: E731
        xoc = lambda: zip(xs, opens, closes)  # NOQA: E731
        iohlc = lambda: zip(xs, opens, highs, lows, closes)  # NOQA: E731

        colorup = self.colorup if fillup else "None"
        colordown = self.colordown if filldown else "None"
        colord = {True: colorup, False: colordown}
        colors = [colord[o < c] for o, c in oc()]

        edgecolord = {True: self.edgeup, False: self.edgedown}
        edgecolors = [edgecolord[o < c] for o, c in oc()]

        tickcolord = {True: self.tickup, False: self.tickdown}
        tickcolors = [tickcolord[o < c] for o, c in oc()]

        delta = width / 2 - edgeadjust

        def barbox(i, open_, close):
            # delta seen as closure
            left, right = i - delta, i + delta
            open_ = open_ * scaling + bot
            close = close * scaling + bot
            return (left, open_), (left, close), (right, close), (right, open_)

        barareas = [barbox(i, o, c) for i, o, c in xoc()]

        def tup(i, open_, high, close):
            high = high * scaling + bot
            open_ = open_ * scaling + bot
            close = close * scaling + bot

            return (i, high), (i, max(open_, close))

        tickrangesup = [tup(i, o, h, c) for i, o, h, low, c in iohlc()]

        def tdown(i, open_, low, close):
            low = low * scaling + bot
            open_ = open_ * scaling + bot
            close = close * scaling + bot

            return (i, low), (i, min(open_, close))

        tickrangesdown = [tdown(i, o, low, c) for i, o, h, low, c in iohlc()]

        # Extra variables for the collections
        useaa = (0,)  # use tuple here
        lw = (0.5,)  # and here
        tlw = (tickwidth,)

        # Bar collection for the candles
        barcol = mcol.PolyCollection(
            barareas,
            facecolors=colors,
            edgecolors=edgecolors,
            antialiaseds=useaa,
            linewidths=lw,
            label=label,
            **kwargs,
        )

        # LineCollections have a higher zorder than PolyCollections
        # to ensure the edges of the bars are not overwriten by the Lines
        # we need to put the bars slightly over the LineCollections
        kwargs["zorder"] = barcol.get_zorder() * 0.9999

        # Up/down ticks from the body
        tickcol = mcol.LineCollection(
            tickrangesup + tickrangesdown,
            colors=tickcolors,
            linewidths=tlw,
            antialiaseds=useaa,
            **kwargs,
        )

        # return barcol, tickcol
        return barcol, tickcol


def plot_candlestick(
    ax,
    x,
    opens,
    highs,
    lows,
    closes,
    colorup="k",
    colordown="r",
    edgeup=None,
    edgedown=None,
    tickup=None,
    tickdown=None,
    width=1,
    tickwidth=1.25,
    edgeadjust=0.05,
    edgeshading=-10,
    alpha=1.0,
    label="_nolegend",
    fillup=True,
    filldown=True,
    **kwargs,
):
    """Plot candlestick chart on given axes.

    Convenience function that creates a CandlestickPlotHandler and returns
    the matplotlib collections for the candlestick chart.

    Args:
        ax: Matplotlib axes object to add collections to.
        x: Array of x-axis coordinates (typically bar indices).
        opens: Array of opening prices.
        highs: Array of high prices.
        lows: Array of low prices.
        closes: Array of closing prices.
        colorup: Color for up bars (close > open). Default is "k" (black).
        colordown: Color for down bars (close < open). Default is "r" (red).
        edgeup: Edge color for up bars. If None, derived from colorup with shading.
        edgedown: Edge color for down bars. If None, derived from colordown with shading.
        tickup: Color for up tick marks (wicks). If None, uses edgeup.
        tickdown: Color for down tick marks (wicks). If None, uses edgedown.
        width: Width of candlestick bodies. Default is 1.
        tickwidth: Width of candlestick wicks. Default is 1.25.
        edgeadjust: Adjustment for edge width. Default is 0.05.
        edgeshading: Shading factor for edge colors. Default is -10.
        alpha: Transparency level (0-1). Default is 1.0.
        label: Label for legend. Default is "_nolegend".
        fillup: Whether to fill up bars. Default is True.
        filldown: Whether to fill down bars. Default is True.
        **kwargs: Additional keyword arguments passed to collections.

    Returns:
        Tuple of (barcol, tickcol): PolyCollection for bodies and LineCollection for wicks.
    """
    chandler = CandlestickPlotHandler(
        ax,
        x,
        opens,
        highs,
        lows,
        closes,
        colorup,
        colordown,
        edgeup,
        edgedown,
        tickup,
        tickdown,
        width,
        tickwidth,
        edgeadjust,
        edgeshading,
        alpha,
        label,
        fillup,
        filldown,
        **kwargs,
    )

    # Return the collections.
    # The barcol goes first because it
    # is the larger, has the dominant zorder and defines the legend
    return chandler.barcol, chandler.tickcol


class VolumePlotHandler:
    """Handler for creating and managing volume plot collections.

    This class creates matplotlib collections for rendering volume bars
    with customizable colors for up and down periods based on price movement.

    Attributes:
        legend_vols: Sample volumes for legend rendering.
        legend_opens: Sample open prices for legend rendering.
        legend_closes: Sample close prices for legend rendering.
        colorup: RGBA color for up volume bars (close > open).
        colordown: RGBA color for down volume bars (close < open).
        edgeup: RGBA edge color for up bars.
        edgedown: RGBA edge color for down bars.
        barcol: PolyCollection containing the volume bars.
    """

    legend_vols = [0.5, 1.0, 0.75]
    legend_opens = [0, 1, 0]
    legend_closes = [1, 0, 1]

    def __init__(
        self,
        ax,
        x,
        opens,
        closes,
        volumes,
        colorup="k",
        colordown="r",
        edgeup=None,
        edgedown=None,
        edgeshading=-5,
        edgeadjust=0.05,
        width=1,
        alpha=1.0,
        **kwargs,
    ):
        """Initialize the volume plot handler.

        Args:
            ax: Matplotlib axes object to add collections to.
            x: Array of x-axis coordinates (typically bar indices).
            opens: Array of opening prices.
            closes: Array of closing prices.
            volumes: Array of volume values.
            colorup: Color for up volume bars (close > open). Default is "k" (black).
            colordown: Color for down volume bars (close < open). Default is "r" (red).
            edgeup: Edge color for up bars. If None, derived from colorup with shading.
            edgedown: Edge color for down bars. If None, derived from colordown with shading.
            edgeshading: Shading factor for edge colors. Default is -5.
            edgeadjust: Adjustment for edge width. Default is 0.05.
            width: Width of volume bars. Default is 1.
            alpha: Transparency level (0-1). Default is 1.0.
            **kwargs: Additional keyword arguments passed to collections.

        Raises:
            ValueError: If color conversion fails.
        """
        # Manage the up/down colors
        r, g, b = mcolors.colorConverter.to_rgb(colorup)
        self.colorup = r, g, b, alpha
        r, g, b = mcolors.colorConverter.to_rgb(colordown)
        self.colordown = r, g, b, alpha

        # Prepare the edge colors
        if not edgeup:
            self.edgeup = shade_color(self.colorup, edgeshading)
        else:
            r, g, b = mcolors.colorConverter.to_rgb(edgeup)
            self.edgeup = r, g, b, alpha

        if not edgedown:
            self.edgedown = shade_color(self.colordown, edgeshading)
        else:
            r, g, b = mcolors.colorConverter.to_rgb(edgedown)
            self.edgedown = r, g, b, alpha

        corners = (0, 0), (len(closes), max(volumes))
        ax.update_datalim(corners)
        ax.autoscale_view()

        self.barcol = self.barcollection(
            x, opens, closes, volumes, width=width, edgeadjust=edgeadjust, **kwargs
        )

        # add to axes
        ax.add_collection(self.barcol)

        # Add a legend handler for this object
        mlegend.Legend.update_default_handler_map({self.barcol: self})

    def legend_artist(self, legend, orig_handle, fontsize, handlebox):
        """Create a custom legend artist for volume plots.

        Args:
            legend: The legend object being created.
            orig_handle: The original handle for which the artist is created.
            fontsize: The font size for the legend.
            handlebox: The handlebox container for positioning the legend artist.

        Returns:
            barcol: The volume bar collection for the legend.
        """
        x0 = handlebox.xdescent
        y0 = handlebox.ydescent
        width = handlebox.width / len(self.legend_vols)
        height = handlebox.height

        # Generate the x-axis coordinates (handlebox based)
        xs = [x0 + width * (i + 0.5) for i in range(len(self.legend_vols))]

        barcol = self.barcollection(
            xs,
            self.legend_opens,
            self.legend_closes,
            self.legend_vols,
            width=width,
            vscaling=height,
            vbot=y0,
        )

        barcol.set_transform(handlebox.get_transform())
        handlebox.add_artist(barcol)

        return barcol

    def barcollection(
        self, x, opens, closes, vols, width, edgeadjust=0, vscaling=1.0, vbot=0, **kwargs
    ):
        """Create matplotlib collection for volume bars.

        Args:
            x: Array of x-axis coordinates.
            opens: Array of opening prices.
            closes: Array of closing prices.
            vols: Array of volume values.
            width: Width of volume bars.
            edgeadjust: Adjustment for edge width. Default is 0.
            vscaling: Vertical scaling factor. Default is 1.0.
            vbot: Bottom offset for vertical positioning. Default is 0.
            **kwargs: Additional keyword arguments passed to collection.

        Returns:
            barcol: PolyCollection containing the volume bars.
        """
        # Prepare the data
        openclose = lambda: zip(opens, closes)  # NOQA: E731

        # Calculate bars colors
        colord = {True: self.colorup, False: self.colordown}
        colors = [colord[open_ < close] for open_, close in openclose()]
        edgecolord = {True: self.edgeup, False: self.edgedown}
        edgecolors = [edgecolord[open_ < close] for open_, close in openclose()]

        # bar width to the sides
        delta = width / 2 - edgeadjust

        # small auxiliary func to return the bar coordinates
        def volbar(i, v):
            left, right = i - delta, i + delta
            v = vbot + v * vscaling
            return (left, vbot), (left, v), (right, v), (right, vbot)

        barareas = [volbar(i, v) for i, v in zip(x, vols)]
        barcol = mcol.PolyCollection(
            barareas,
            facecolors=colors,
            edgecolors=edgecolors,
            antialiaseds=(0,),
            linewidths=(0.5,),
            **kwargs,
        )

        return barcol


def plot_volume(
    ax,
    x,
    opens,
    closes,
    volumes,
    colorup="k",
    colordown="r",
    edgeup=None,
    edgedown=None,
    edgeshading=-5,
    edgeadjust=0.05,
    width=1,
    alpha=1.0,
    **kwargs,
):
    """Plot volume chart on given axes.

    Convenience function that creates a VolumePlotHandler and returns
    the matplotlib collection for the volume chart.

    Args:
        ax: Matplotlib axes object to add collections to.
        x: Array of x-axis coordinates (typically bar indices).
        opens: Array of opening prices.
        closes: Array of closing prices.
        volumes: Array of volume values.
        colorup: Color for up volume bars (close > open). Default is "k" (black).
        colordown: Color for down volume bars (close < open). Default is "r" (red).
        edgeup: Edge color for up bars. If None, derived from colorup with shading.
        edgedown: Edge color for down bars. If None, derived from colordown with shading.
        edgeshading: Shading factor for edge colors. Default is -5.
        edgeadjust: Adjustment for edge width. Default is 0.05.
        width: Width of volume bars. Default is 1.
        alpha: Transparency level (0-1). Default is 1.0.
        **kwargs: Additional keyword arguments passed to collection.

    Returns:
        Tuple containing the volume bar collection.
    """
    vhandler = VolumePlotHandler(
        ax,
        x,
        opens,
        closes,
        volumes,
        colorup,
        colordown,
        edgeup,
        edgedown,
        edgeshading,
        edgeadjust,
        width,
        alpha,
        **kwargs,
    )

    return (vhandler.barcol,)


class OHLCPlotHandler:
    """Handler for creating and managing OHLC (Open-High-Low-Close) plot collections.

    This class creates matplotlib line collections for rendering OHLC bar charts
    with customizable colors for up and down bars.

    Attributes:
        legend_opens: Open prices for legend sample bars.
        legend_highs: High prices for legend sample bars.
        legend_lows: Low prices for legend sample bars.
        legend_closes: Close prices for legend sample bars.
        colorup: RGBA color for up bars (close > open).
        colordown: RGBA color for down bars (close < open).
        barcol: LineCollection containing the vertical high-low lines.
        opencol: LineCollection containing the open tick marks.
        closecol: LineCollection containing the close tick marks.
    """

    legend_opens = [0.50, 0.50, 0.50]
    legend_highs = [1.00, 1.00, 1.00]
    legend_lows = [0.00, 0.00, 0.00]
    legend_closes = [0.80, 0.20, 0.90]

    def __init__(
        self,
        ax,
        x,
        opens,
        highs,
        lows,
        closes,
        colorup="k",
        colordown="r",
        width=1,
        tickwidth=0.5,
        alpha=1.0,
        label="_nolegend",
        **kwargs,
    ):
        """Initialize the OHLC plot handler.

        Args:
            ax: Matplotlib axes object to add collections to.
            x: Array of x-axis coordinates (typically bar indices).
            opens: Array of opening prices.
            highs: Array of high prices.
            lows: Array of low prices.
            closes: Array of closing prices.
            colorup: Color for up bars (close > open). Default is "k" (black).
            colordown: Color for down bars (close < open). Default is "r" (red).
            width: Width of vertical high-low lines. Default is 1.
            tickwidth: Width of open/close tick marks. Default is 0.5.
            alpha: Transparency level (0-1). Default is 1.0.
            label: Label for legend. Default is "_nolegend".
            **kwargs: Additional keyword arguments passed to collections.

        Raises:
            ValueError: If color conversion fails.
        """
        # Manager up/down bar colors
        r, g, b = mcolors.colorConverter.to_rgb(colorup)
        self.colorup = r, g, b, alpha
        r, g, b = mcolors.colorConverter.to_rgb(colordown)
        self.colordown = r, g, b, alpha

        bcol, ocol, ccol = self.barcollection(
            x, opens, highs, lows, closes, width=width, tickwidth=tickwidth, label=label, **kwargs
        )

        self.barcol = bcol
        self.opencol = ocol
        self.closecol = ccol

        # add collections to the axis and return them
        ax.add_collection(self.barcol)
        ax.add_collection(self.opencol)
        ax.add_collection(self.closecol)

        # Update the axis
        ax.update_datalim(((0, min(lows)), (len(opens), max(highs))))
        ax.autoscale_view()

        # Add self as legend handler for this object
        mlegend.Legend.update_default_handler_map({self.barcol: self})

    def legend_artist(self, legend, orig_handle, fontsize, handlebox):
        """Create a custom legend artist for OHLC plots.

        Args:
            legend: The legend object being created.
            orig_handle: The original handle for which the artist is created.
            fontsize: The font size for the legend.
            handlebox: The handlebox container for positioning the legend artist.

        Returns:
            Tuple of (barcol, opencol, closecol): The line collections for the legend.
        """
        x0 = handlebox.xdescent
        y0 = handlebox.ydescent
        width = handlebox.width / len(self.legend_opens)
        height = handlebox.height

        # Generate the x-axis coordinates (handlebox based)
        xs = [x0 + width * (i + 0.5) for i in range(len(self.legend_opens))]

        barcol, opencol, closecol = self.barcollection(
            xs,
            self.legend_opens,
            self.legend_highs,
            self.legend_lows,
            self.legend_closes,
            width=1.5,
            tickwidth=2,
            scaling=height,
            bot=y0,
        )

        barcol.set_transform(handlebox.get_transform())
        handlebox.add_artist(barcol)
        # opencol.set_transform(handlebox.get_transform())
        handlebox.add_artist(opencol)
        # closecol.set_transform(handlebox.get_transform())
        handlebox.add_artist(closecol)

        return barcol, opencol, closecol

    def barcollection(
        self,
        xs,
        opens,
        highs,
        lows,
        closes,
        width,
        tickwidth,
        label="_nolegend",
        scaling=1.0,
        bot=0,
        **kwargs,
    ):
        """Create matplotlib collections for OHLC bars and tick marks.

        Args:
            xs: Array of x-axis coordinates.
            opens: Array of opening prices.
            highs: Array of high prices.
            lows: Array of low prices.
            closes: Array of closing prices.
            width: Width of vertical high-low lines.
            tickwidth: Width of open/close tick marks.
            label: Label for legend. Default is "_nolegend".
            scaling: Vertical scaling factor. Default is 1.0.
            bot: Bottom offset for vertical positioning. Default is 0.
            **kwargs: Additional keyword arguments passed to collections.

        Returns:
            Tuple of (barcol, opencol, closecol): LineCollection for bars,
                open ticks, and close ticks.
        """
        # Prepack different zips of the series values
        ihighlow = lambda: zip(xs, highs, lows)  # NOQA: E731
        iopen = lambda: zip(xs, opens)  # NOQA: E731
        iclose = lambda: zip(xs, closes)  # NOQA: E731
        openclose = lambda: zip(opens, closes)  # NOQA: E731

        colord = {True: self.colorup, False: self.colordown}
        colors = [colord[open_ < close] for open_, close in openclose()]

        # Extra variables for the collections
        useaa = (0,)
        lw = (width,)
        tlw = (tickwidth,)

        # Calculate the barranges
        def barrange(i, high, low):
            return (i, low * scaling + bot), (i, high * scaling + bot)

        barranges = [barrange(i, high, low) for i, high, low in ihighlow()]

        barcol = mcol.LineCollection(
            barranges, colors=colors, linewidths=lw, antialiaseds=useaa, label=label, **kwargs
        )

        def tickopen(i, open_):
            open_ = open_ * scaling + bot
            return (i - tickwidth, open_), (i, open_)

        openticks = [tickopen(i, open_) for i, open_ in iopen()]
        opencol = mcol.LineCollection(
            openticks,
            colors=colors,
            antialiaseds=useaa,
            linewidths=tlw,
            label="_nolegend",
            **kwargs,
        )

        def tickclose(i, close):
            close = close * scaling + bot
            return (i, close), (i + tickwidth, close)

        closeticks = [tickclose(i, close) for i, close in iclose()]
        closecol = mcol.LineCollection(
            closeticks,
            colors=colors,
            antialiaseds=useaa,
            linewidths=tlw,
            label="_nolegend",
            **kwargs,
        )

        # return barcol, tickcol
        return barcol, opencol, closecol


def plot_ohlc(
    ax,
    x,
    opens,
    highs,
    lows,
    closes,
    colorup="k",
    colordown="r",
    width=1.5,
    tickwidth=0.5,
    alpha=1.0,
    label="_nolegend",
    **kwargs,
):
    """Plot OHLC (Open-High-Low-Close) chart on given axes.

    Convenience function that creates an OHLCPlotHandler and returns
    the matplotlib collections for the OHLC chart.

    Args:
        ax: Matplotlib axes object to add collections to.
        x: Array of x-axis coordinates (typically bar indices).
        opens: Array of opening prices.
        highs: Array of high prices.
        lows: Array of low prices.
        closes: Array of closing prices.
        colorup: Color for up bars (close > open). Default is "k" (black).
        colordown: Color for down bars (close < open). Default is "r" (red).
        width: Width of vertical high-low lines. Default is 1.5.
        tickwidth: Width of open/close tick marks. Default is 0.5.
        alpha: Transparency level (0-1). Default is 1.0.
        label: Label for legend. Default is "_nolegend".
        **kwargs: Additional keyword arguments passed to collections.

    Returns:
        Tuple of (barcol, opencol, closecol): LineCollection for bars,
            open ticks, and close ticks.
    """
    handler = OHLCPlotHandler(
        ax,
        x,
        opens,
        highs,
        lows,
        closes,
        colorup,
        colordown,
        width,
        tickwidth,
        alpha,
        label,
        **kwargs,
    )

    return handler.barcol, handler.opencol, handler.closecol


class LineOnClosePlotHandler:
    """Handler for creating and managing line-on-close plot collections.

    This class creates matplotlib line objects for rendering a simple line
    chart of closing prices.

    Attributes:
        legend_closes: Sample close prices for legend rendering.
        color: Color of the line.
        alpha: Transparency level (0-1).
        loc: Line2D object containing the close price line.
    """

    legend_closes = [0.00, 0.66, 0.33, 1.00]

    def __init__(self, ax, x, closes, color="k", width=1, alpha=1.0, label="_nolegend", **kwargs):
        """Initialize the line-on-close plot handler.

        Args:
            ax: Matplotlib axes object to add the line to.
            x: Array of x-axis coordinates (typically bar indices).
            closes: Array of closing prices.
            color: Color of the line. Default is "k" (black).
            width: Width of the line. Default is 1.
            alpha: Transparency level (0-1). Default is 1.0.
            label: Label for legend. Default is "_nolegend".
            **kwargs: Additional keyword arguments passed to Line2D.
        """
        self.color = color
        self.alpha = alpha

        (self.loc,) = self.barcollection(x, closes, width=width, label=label, **kwargs)

        # add collections to the axis and return them
        ax.add_line(self.loc)

        # Update the axis
        ax.update_datalim(((x[0], min(closes)), (x[-1], max(closes))))
        ax.autoscale_view()

        # Add self as legend handler for this object
        mlegend.Legend.update_default_handler_map({self.loc: self})

    def legend_artist(self, legend, orig_handle, fontsize, handlebox):
        """Create a custom legend artist for line-on-close plots.

        Args:
            legend: The legend object being created.
            orig_handle: The original handle for which the artist is created.
            fontsize: The font size for the legend.
            handlebox: The handlebox container for positioning the legend artist.

        Returns:
            Tuple containing the line collection for the legend.
        """
        x0 = handlebox.xdescent
        y0 = handlebox.ydescent
        width = handlebox.width / len(self.legend_closes)
        height = handlebox.height

        # Generate the x-axis coordinates (handlebox based)
        xs = [x0 + width * (i + 0.5) for i in range(len(self.legend_closes))]

        (linecol,) = self.barcollection(xs, self.legend_closes, width=1.5, scaling=height, bot=y0)

        linecol.set_transform(handlebox.get_transform())
        handlebox.add_artist(linecol)

        return (linecol,)

    def barcollection(self, xs, closes, width, label="_nolegend", scaling=1.0, bot=0, **kwargs):
        """Create matplotlib line object for close prices.

        Args:
            xs: Array of x-axis coordinates.
            closes: Array of closing prices.
            width: Width of the line.
            label: Label for legend. Default is "_nolegend".
            scaling: Vertical scaling factor. Default is 1.0.
            bot: Bottom offset for vertical positioning. Default is 0.
            **kwargs: Additional keyword arguments passed to Line2D.

        Returns:
            Tuple containing the Line2D object.
        """
        # Prepack different zips of the series values
        scaled = [close * scaling + bot for close in closes]

        loc = mlines.Line2D(
            xs, scaled, color=self.color, lw=width, label=label, alpha=self.alpha, **kwargs
        )

        return (loc,)


def plot_lineonclose(ax, x, closes, color="k", width=1.5, alpha=1.0, label="_nolegend", **kwargs):
    """Plot line-on-close chart on given axes.

    Convenience function that creates a LineOnClosePlotHandler and returns
    the matplotlib line object for the line chart.

    Args:
        ax: Matplotlib axes object to add the line to.
        x: Array of x-axis coordinates (typically bar indices).
        closes: Array of closing prices.
        color: Color of the line. Default is "k" (black).
        width: Width of the line. Default is 1.5.
        alpha: Transparency level (0-1). Default is 1.0.
        label: Label for legend. Default is "_nolegend".
        **kwargs: Additional keyword arguments passed to Line2D.

    Returns:
        Tuple containing the Line2D object.
    """
    handler = LineOnClosePlotHandler(
        ax, x, closes, color=color, width=width, alpha=alpha, label=label, **kwargs
    )

    return (handler.loc,)
