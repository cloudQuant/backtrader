#!/usr/bin/env python
"""
Plotly-based plotting for backtrader.

This module provides high-performance interactive charts using Plotly,
which handles large datasets much better than matplotlib.
"""
import bisect
import collections
import datetime
import math

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..parameters import ParameterDescriptor, ParameterizedBase
from ..utils.date import num2date
from ..utils.py3 import range
from .scheme import PlotScheme

# Tableau color schemes
TABLEAU10 = [
    "blue",
    "darkorange",
    "green",
    "crimson",
    "mediumpurple",
    "saddlebrown",
    "orchid",
    "gray",
    "olive",
    "mediumturquoise",
]

TABLEAU20 = [
    "steelblue",
    "lightsteelblue",
    "darkorange",
    "peachpuff",
    "green",
    "lightgreen",
    "crimson",
    "lightcoral",
    "mediumpurple",
    "thistle",
    "saddlebrown",
    "rosybrown",
    "orchid",
    "lightpink",
    "gray",
    "lightgray",
    "olive",
    "palegoldenrod",
    "mediumturquoise",
    "paleturquoise",
]

TABLEAU10_LIGHT = [
    "lightsteelblue",
    "peachpuff",
    "lightgreen",
    "lightcoral",
    "thistle",
    "rosybrown",
    "lightpink",
    "lightgray",
    "palegoldenrod",
    "paleturquoise",
]

# Color index mapping for optimized visual order
TAB10_INDEX = [3, 0, 2, 1, 2, 4, 5, 6, 7, 8, 9]

# Color mapper from matplotlib to plotly
COLOR_MAPPER = {
    "b": "rgb(0, 0, 255)",
    "blue": "rgb(0, 0, 255)",
    "g": "rgb(0, 128, 0)",
    "green": "rgb(0, 128, 0)",
    "r": "rgb(255, 0, 0)",
    "red": "rgb(255, 0, 0)",
    "c": "rgb(0, 255, 255)",
    "cyan": "rgb(0, 255, 255)",
    "m": "rgb(255, 0, 255)",
    "magenta": "rgb(255, 0, 255)",
    "y": "rgb(255, 255, 0)",
    "yellow": "rgb(255, 255, 0)",
    "k": "rgb(0, 0, 0)",
    "black": "rgb(0, 0, 0)",
    "w": "rgb(255, 255, 255)",
    "white": "rgb(255, 255, 255)",
    "steelblue": "rgb(70, 130, 180)",
    "darkorange": "rgb(255, 140, 0)",
    "crimson": "rgb(220, 20, 60)",
    "mediumpurple": "rgb(147, 112, 219)",
    "saddlebrown": "rgb(139, 69, 19)",
    "orchid": "rgb(218, 112, 214)",
    "olive": "rgb(128, 128, 0)",
    "mediumturquoise": "rgb(72, 209, 204)",
    "lightsteelblue": "rgb(176, 196, 222)",
    "peachpuff": "rgb(255, 218, 185)",
    "lightgreen": "rgb(144, 238, 144)",
    "lightcoral": "rgb(240, 128, 128)",
    "thistle": "rgb(216, 191, 216)",
    "rosybrown": "rgb(188, 143, 143)",
    "lightpink": "rgb(255, 182, 193)",
    "lightgray": "rgb(211, 211, 211)",
    "palegoldenrod": "rgb(238, 232, 170)",
    "paleturquoise": "rgb(175, 238, 238)",
}


def get_color_scheme(name="tableau10"):
    """Get color scheme by name.

    Args:
        name: Color scheme name ('tableau10', 'tableau20', 'tableau10_light')

    Returns:
        list: Color list
    """
    schemes = {
        "tableau10": TABLEAU10,
        "tableau20": TABLEAU20,
        "tableau10_light": TABLEAU10_LIGHT,
    }
    return schemes.get(name, TABLEAU10)


def wrap_legend_text(text, max_width=16):
    """Wrap legend text with automatic line breaks.

    Reference: backtrader_plotly/plotter.py:695-702

    Args:
        text: Original text
        max_width: Maximum character width per line

    Returns:
        str: Processed text with <br> separators for long lines
    """
    if text is None:
        return ""
    text = str(text)

    # Remove existing newlines
    text = text.replace("\n", "")

    if len(text) <= max_width:
        return text

    # Split by max_width
    return "<br>".join(text[i : i + max_width] for i in range(0, len(text), max_width))


class PlotlyScheme(PlotScheme):
    """Extended scheme for Plotly plotting with optimized colors.

    Extends PlotScheme with Plotly-specific settings for interactive charts,
    including theme selection, range slider configuration, and optimized
    color schemes for better visual presentation in web-based plots.

    Attributes:
        plotly_theme (str): Plotly theme name (e.g., 'plotly_white').
        rangeslider (bool): Whether to show range slider for navigation.
        rangeslider_preview (bool): Whether to show preview in range slider.
        height_ratios (list): Height ratios for subplots [price, volume, indicator].
        barup (str): Color for bullish bars (default: red for Chinese market).
        barupfill (bool): Whether bullish candles are filled.
        buymarker_color (str): Color for buy markers.
        buymarker_size (int): Size of buy markers.
        sellmarker_color (str): Color for sell markers.
        sellmarker_size (int): Size of sell markers.
        equity_color (str): Color for equity curve.
        decimal_places (int): Number of decimal places for price display.
        max_legend_text_width (int): Maximum legend text width before wrapping.
        color_scheme (str): Color scheme name ('tableau10', 'tableau20', 'tableau10_light').
        fillalpha (float): Fill area transparency (0-1).
    """

    def __init__(self, **kwargs):
        """Initialize PlotlyScheme with Plotly-specific defaults.

        Sets up optimized color schemes and plotting configurations for
        interactive Plotly charts, including Chinese market color conventions
        (red for up, green for down).

        Args:
            **kwargs: Optional keyword arguments to override defaults.
                - decimal_places (int): Price decimal places (default: 5)
                - max_legend_text_width (int): Legend text width (default: 16)
                - color_scheme (str): Color scheme name (default: 'tableau10')
                - fillalpha (float): Fill transparency (default: 0.20)
        """
        super().__init__()
        # Plotly specific settings
        self.plotly_theme = "plotly_white"
        self.rangeslider = True
        self.rangeslider_preview = False
        self.height_ratios = [3, 1, 1]  # price, volume, indicator

        # Optimized color scheme (Chinese market: red up, green down)
        self.barup = "#E74C3C"  # Red for bullish
        self.bardown = "#27AE60"  # Green for bearish
        self.barupfill = True
        self.bardownfill = True

        # Volume colors
        self.volup = "rgba(231, 76, 60, 0.5)"  # Red transparent
        self.voldown = "rgba(39, 174, 96, 0.5)"  # Green transparent

        # Line colors for indicators (legacy, will use color_scheme)
        self.linecolors = [
            "#3498DB",  # Blue
            "#E67E22",  # Orange
            "#9B59B6",  # Purple
            "#1ABC9C",  # Teal
            "#F39C12",  # Yellow
            "#E91E63",  # Pink
            "#00BCD4",  # Cyan
            "#FF5722",  # Deep Orange
        ]

        # Buy/Sell marker colors
        self.buymarker_color = "#E74C3C"  # Red
        self.sellmarker_color = "#27AE60"  # Green
        self.buymarker_size = 12
        self.sellmarker_size = 12

        # Equity curve
        self.equity_color = "#3498DB"  # Blue

        # New parameters from backtrader_plotly
        # Decimal places for price display
        self.decimal_places = kwargs.get("decimal_places", 5)

        # Maximum legend text width before wrapping
        self.max_legend_text_width = kwargs.get("max_legend_text_width", 16)

        # Color scheme selection
        self.color_scheme = kwargs.get("color_scheme", "tableau10")

        # Fill area transparency
        self.fillalpha = kwargs.get("fillalpha", 0.20)

        # Tableau color schemes
        self.tableau10 = TABLEAU10
        self.tableau20 = TABLEAU20
        self.tableau10_light = TABLEAU10_LIGHT

        # Color index mapping for optimized visual order
        self.tab10_index = TAB10_INDEX

    def get_colors(self):
        """Get current color scheme colors.

        Returns:
            list: Color list based on current color_scheme setting
        """
        return getattr(self, self.color_scheme, self.tableau10)

    def color(self, idx):
        """Get color for given index using tab10_index mapping.

        Uses tab10_index mapping to optimize visual order of colors.

        Args:
            idx: Color index

        Returns:
            str: Color name or value
        """
        colors = self.get_colors()
        colidx = self.tab10_index[idx % len(self.tab10_index)]
        return colors[colidx % len(colors)]


class PlotlyPlot(ParameterizedBase):
    """
    Plotly-based plotter for backtrader strategies.

    Provides interactive charts with:
    - Candlestick/OHLC/Line charts
    - Volume bars
    - Indicator subplots
    - Buy/Sell markers
    - Range slider for navigation
    """

    scheme = ParameterDescriptor(default=PlotlyScheme(), doc="Plotting scheme")

    def __init__(self, **kwargs):
        """Initialize PlotlyPlot with optional scheme overrides.

        Args:
            **kwargs: Optional keyword arguments to override scheme parameters.
                Any parameter name matching a PlotlyScheme attribute will
                update that attribute in the scheme.

        Example:
            >>> plotter = PlotlyPlot(style='candle', volume=True)
        """
        super().__init__()
        for pname, pvalue in kwargs.items():
            if hasattr(self.p.scheme, pname):
                setattr(self.p.scheme, pname, pvalue)

        self.figs = []
        self.data_cache = {}
        self.buysell_markers = []  # Store buy/sell signals

    def _format_value(self, value):
        """Format numeric value with configured decimal places.

        Uses scheme.decimal_places to control precision.

        Args:
            value: Numeric value to format

        Returns:
            str: Formatted value string
        """
        decimal_places = getattr(self.p.scheme, "decimal_places", 5)
        try:
            return f"{float(value):.{decimal_places}f}"
        except (ValueError, TypeError):
            return str(value)

    def _get_tick_format(self):
        """Get y-axis tick format string.

        Returns:
            str: Format string for axis ticks (e.g., '.5f')
        """
        decimal_places = getattr(self.p.scheme, "decimal_places", 5)
        return f".{decimal_places}f"

    def _format_label(self, label):
        """Format legend label with automatic wrapping.

        Args:
            label: Original label text

        Returns:
            str: Wrapped label text
        """
        max_width = getattr(self.p.scheme, "max_legend_text_width", 16)
        return wrap_legend_text(label, max_width)

    def fill_between(
        self, fig, row, x, y1, y2, secondary_y=False, color=None, opacity=None, name="", where=None
    ):
        """Draw filled area between two lines.

        Reference: backtrader_plotly/plotter.py:718-750

        Args:
            fig: Plotly figure object
            row: Subplot row number
            x: x-axis data
            y1: Upper boundary data
            y2: Lower boundary data
            secondary_y: Whether to use right y-axis
            color: Fill color
            opacity: Fill opacity (default: scheme.fillalpha)
            name: Legend name
            where: Condition mask (optional)
        """
        x = np.array(x)
        y1 = np.array(y1)
        y2 = np.array(y2)

        # Apply condition filter
        if where is not None:
            y2 = np.where(where, y2, y1)

        # Get opacity from scheme if not provided
        if opacity is None:
            opacity = getattr(self.p.scheme, "fillalpha", 0.20)

        # Convert color to RGBA
        if color is not None:
            color = self._to_rgba_color(color, opacity)
        else:
            color = f"rgba(128, 128, 128, {opacity})"

        legendgroup = f"fill_{name}_{row}"

        # Add upper boundary line
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y2,
                name=name,
                legendgroup=legendgroup,
                showlegend=False,
                line=dict(color=color, width=0),
            ),
            row=row,
            col=1,
            secondary_y=secondary_y,
        )

        # Add filled area
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y1,
                name=self._format_label(name) if name else "",
                legendgroup=legendgroup,
                fill="tonexty",
                fillcolor=color,
                line=dict(color=color, width=0),
            ),
            row=row,
            col=1,
            secondary_y=secondary_y,
        )

    def _to_rgba_color(self, color, opacity):
        """Convert color to RGBA format.

        Args:
            color: Color name or rgb string
            opacity: Opacity value (0-1)

        Returns:
            str: rgba(r, g, b, a) format string
        """
        # Check if already rgba
        if isinstance(color, str) and color.startswith("rgba"):
            return color

        # Check color mapper
        if color in COLOR_MAPPER:
            rgb = COLOR_MAPPER[color]
        else:
            rgb = self._to_plotly_color(color)

        # Extract RGB values and add opacity
        if rgb and rgb.startswith("rgb("):
            return f"rgba{rgb[3:-1]}, {opacity})"

        return f"rgba(128, 128, 128, {opacity})"

    def plot(
        self,
        strategy,
        figid=0,
        numfigs=1,
        iplot=True,
        start=None,
        end=None,
        use=None,
        **kwargs,
    ):
        """
        Plot the strategy results using Plotly.

        Args:
            strategy: The strategy to plot
            figid: Figure ID for multiple figures
            numfigs: Number of figures to split into
            iplot: If True, display inline in notebook
            start: Start index or datetime
            end: End index or datetime
            use: Ignored (matplotlib backend parameter)

        Returns:
            List of Plotly figure objects
        """
        if not strategy.datas:
            return []

        if not len(strategy):
            return []

        # Sort indicators and observers
        self._sortdataindicators(strategy)

        # Collect buy/sell signals
        self._collect_buysell_signals(strategy)

        # Get datetime range
        st_dtime = strategy.lines.datetime.plot()
        if start is None:
            start = 0
        if end is None:
            end = len(st_dtime)

        if isinstance(start, datetime.date):
            start = bisect.bisect_left(st_dtime, self._date2num(start))
        if isinstance(end, datetime.date):
            end = bisect.bisect_right(st_dtime, self._date2num(end))

        if end < 0:
            end = len(st_dtime) + 1 + end

        # Create figures
        figs = []
        for numfig in range(numfigs):
            # Calculate range for this figure
            slen = len(st_dtime[start:end])
            d, m = divmod(slen, numfigs)
            a = d * numfig + start
            if numfig == (numfigs - 1):
                d += m
            b = a + d

            fig = self._create_figure(strategy, a, b, st_dtime)
            figs.append(fig)
            self.figs.append(fig)

        return figs

    def _date2num(self, dt):
        """Convert datetime to matplotlib-style number."""
        from .. import date2num

        return date2num(dt)

    def _num2date(self, num):
        """Convert matplotlib-style number to datetime."""
        from .. import num2date

        return num2date(num)

    def _create_figure(self, strategy, pstart, pend, st_dtime):
        """Create a Plotly figure for the given range."""
        # Count rows needed
        n_rows, row_specs, row_heights = self._calc_rows(strategy)

        # Create subplots
        fig = make_subplots(
            rows=n_rows,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.02,
            row_heights=row_heights,
            specs=row_specs,
        )

        # Convert datetime
        xdata = [self._num2date(x) for x in st_dtime[pstart:pend]]
        current_row = 1

        # Plot each data feed
        for data in strategy.datas:
            if not data.plotinfo.plot:
                continue

            # Get OHLCV data
            opens = list(data.open.plotrange(pstart, pend))
            highs = list(data.high.plotrange(pstart, pend))
            lows = list(data.low.plotrange(pstart, pend))
            closes = list(data.close.plotrange(pstart, pend))
            volumes = list(data.volume.plotrange(pstart, pend))

            # Align x data if needed
            data_xdata = xdata
            dts = data.datetime.plot()
            if len(dts) < len(st_dtime):
                # This data has fewer bars, need to align
                data_xdata = [self._num2date(x) for x in data.datetime.plotrange(pstart, pend)]

            # Skip indicators above data (disabled for cleaner chart)
            # for ind in self.dplotsup.get(data, []):
            #     current_row = self._plot_indicator(
            #         fig, ind, data_xdata, pstart, pend, current_row
            #     )

            # Plot main price chart
            current_row = self._plot_data(
                fig, data, data_xdata, opens, highs, lows, closes, volumes, current_row
            )

            # Plot buy/sell signals with price offset
            self._plot_buysell_markers(fig, data, data_xdata, lows, highs, current_row - 1)

            # Skip indicators below data (user requested removal)
            # for ind in self.dplotsdown.get(data, []):
            #     current_row = self._plot_indicator(
            #         fig, ind, data_xdata, pstart, pend, current_row
            #     )

        # Plot equity curve with drawdown at bottom
        current_row = self._plot_equity_curve(fig, strategy, xdata, pstart, pend, current_row)

        # Update layout
        self._update_layout(fig, strategy)

        return fig

    def _calc_rows(self, strategy):
        """Calculate number of rows and their specifications."""
        n_rows = 0
        row_heights = []
        row_specs = []

        # Data feeds and their indicators
        for data in strategy.datas:
            if not data.plotinfo.plot:
                continue

            # Indicators above - disabled for cleaner chart
            # n_up = len(self.dplotsup.get(data, []))
            # n_rows += n_up
            # row_heights.extend([0.5] * n_up)
            # row_specs.extend([[{"secondary_y": False}]] * n_up)

            # Main data (with optional volume overlay)
            n_rows += 1
            row_heights.append(3)
            row_specs.append([{"secondary_y": True}])

            # Volume as separate row if not overlay (smaller height)
            if self.p.scheme.volume and not self.p.scheme.voloverlay:
                n_rows += 1
                row_heights.append(0.6)  # Smaller volume subplot
                row_specs.append([{"secondary_y": False}])

            # Overlaid indicators don't add rows
            for ind in self.dplotsover.get(data, []):
                pass  # These are plotted on the same row as data

        # Equity curve row at bottom (below K-line)
        n_rows += 1
        row_heights.append(1.5)
        row_specs.append([{"secondary_y": False}])

        if n_rows == 0:
            n_rows = 1
            row_heights = [1]
            row_specs = [[{"secondary_y": False}]]

        # Normalize heights
        total = sum(row_heights)
        row_heights = [h / total for h in row_heights]

        return n_rows, row_specs, row_heights

    def _plot_data(self, fig, data, xdata, opens, highs, lows, closes, volumes, row):
        """Plot OHLCV data."""
        datalabel = getattr(data, "_name", "") or "Data"

        # Choose chart style
        style = self.p.scheme.style
        if style.startswith("candle"):
            fig.add_trace(
                go.Candlestick(
                    x=xdata,
                    open=opens,
                    high=highs,
                    low=lows,
                    close=closes,
                    name=datalabel,
                    increasing_line_color=self._to_plotly_color(self.p.scheme.barup),
                    decreasing_line_color=self._to_plotly_color(self.p.scheme.bardown),
                    increasing_fillcolor=self._to_plotly_color(self.p.scheme.barup),
                    decreasing_fillcolor=self._to_plotly_color(self.p.scheme.bardown),
                ),
                row=row,
                col=1,
            )
        elif style.startswith("bar"):
            fig.add_trace(
                go.Ohlc(
                    x=xdata,
                    open=opens,
                    high=highs,
                    low=lows,
                    close=closes,
                    name=datalabel,
                    increasing_line_color=self._to_plotly_color(self.p.scheme.barup),
                    decreasing_line_color=self._to_plotly_color(self.p.scheme.bardown),
                ),
                row=row,
                col=1,
            )
        else:  # line
            fig.add_trace(
                go.Scatter(
                    x=xdata,
                    y=closes,
                    mode="lines",
                    name=datalabel,
                    line=dict(color=self._to_plotly_color(self.p.scheme.loc)),
                ),
                row=row,
                col=1,
            )

        # Plot volume
        if self.p.scheme.volume and max(volumes) > 0:
            colors = [
                self.p.scheme.volup if c >= o else self.p.scheme.voldown
                for o, c in zip(opens, closes)
            ]
            colors = [self._to_plotly_color(c) for c in colors]

            if self.p.scheme.voloverlay:
                # Overlay on price chart - scale down volume to bottom 20% of chart
                max_vol = max(volumes)
                min_price = min(lows)
                max_price = max(highs)
                price_range = max_price - min_price
                # Scale volume to 15% of price range, positioned at bottom
                scale_factor = (price_range * 0.15) / max_vol if max_vol > 0 else 1
                scaled_volumes = [v * scale_factor for v in volumes]
                # Offset to position below price bars
                vol_base = min_price - price_range * 0.02

                fig.add_trace(
                    go.Bar(
                        x=xdata,
                        y=scaled_volumes,
                        base=[vol_base] * len(scaled_volumes),
                        name="Volume",
                        marker_color=colors,
                        opacity=0.6,
                        showlegend=True,
                    ),
                    row=row,
                    col=1,
                )
                row_inc = 1
            else:
                # Separate volume subplot
                fig.add_trace(
                    go.Bar(
                        x=xdata,
                        y=volumes,
                        name="Volume",
                        marker_color=colors,
                        opacity=0.7,
                    ),
                    row=row + 1,
                    col=1,
                )
                row_inc = 2
        else:
            row_inc = 1

        # Plot overlaid indicators
        for ind in self.dplotsover.get(data, []):
            self._plot_indicator_on_ax(fig, ind, xdata, row, is_overlay=True)

        return row + row_inc

    def _plot_indicator(self, fig, ind, xdata, pstart, pend, row, is_observer=False):
        """Plot an indicator in its own subplot."""
        indlabel = ind.plotlabel()
        # Ensure indlabel is a string
        if not isinstance(indlabel, str):
            indlabel = str(ind.__class__.__name__)

        for lineidx in range(ind.size()):
            line = ind.lines[lineidx]
            linealias = ind.lines._getlinealias(lineidx)
            lplot = list(line.plotrange(pstart, pend))

            if not lplot or len(lplot) == 0:
                continue

            # Align data length
            plot_xdata = xdata
            if len(lplot) != len(xdata):
                plot_xdata = xdata[: len(lplot)]

            # Find first valid (non-NaN and non-zero-before-real-data) value
            # Indicators output 0.0 before they have enough data, then jump to real values
            valid_start = 0
            found_nonzero = False
            for i, v in enumerate(lplot):
                if math.isnan(v):
                    continue
                # If we find a non-zero value, that's where real data starts
                if v != 0.0:
                    valid_start = i
                    found_nonzero = True
                    break
                # If all values are 0, we'll check if later values become non-zero

            # If no non-zero found, check if there are any real values
            if not found_nonzero:
                # Find first transition from 0 to non-zero
                for i in range(len(lplot) - 1):
                    if lplot[i] == 0.0 and lplot[i + 1] != 0.0 and not math.isnan(lplot[i + 1]):
                        valid_start = i + 1
                        found_nonzero = True
                        break

            # Skip leading invalid portion (zeros before real data)
            if valid_start > 0:
                lplot = lplot[valid_start:]
                plot_xdata = plot_xdata[valid_start:]

            if not lplot:
                continue

            # Replace NaN with None for Plotly to skip
            lplot = [None if math.isnan(v) else v for v in lplot]

            # Get line plot info
            lineplotinfo = getattr(ind.plotlines, linealias, None)
            if lineplotinfo is None:
                lineplotinfo = getattr(ind.plotlines, "_%d" % lineidx, None)

            # Get color
            color = None
            if lineplotinfo:
                color = lineplotinfo._get("color", None)
            if color is None:
                color = self.p.scheme.color(lineidx)

            # Get line style
            linestyle = "solid"
            if lineplotinfo:
                ls = lineplotinfo._get("ls", None) or lineplotinfo._get("linestyle", None)
                if ls == "--":
                    linestyle = "dash"
                elif ls == ":":
                    linestyle = "dot"
                elif ls == "-.":
                    linestyle = "dashdot"

            label = f"{indlabel} - {linealias}" if ind.size() > 1 else indlabel

            fig.add_trace(
                go.Scatter(
                    x=plot_xdata,
                    y=lplot,
                    mode="lines",
                    name=label,
                    line=dict(color=self._to_plotly_color(color), dash=linestyle),
                ),
                row=row,
                col=1,
            )

        # Plot horizontal lines
        hlines = ind.plotinfo._get("plothlines", None) or []
        if not hlines:
            hlines = ind.plotinfo._get("plotyhlines", None) or []
        for hline in hlines:
            fig.add_hline(
                y=hline,
                line_dash="dash",
                line_color=self._to_plotly_color(self.p.scheme.hlinescolor),
                row=row,
                col=1,
            )

        return row + 1

    def _plot_indicator_on_ax(self, fig, ind, xdata, row, is_overlay=False):
        """Plot an indicator overlaid on existing subplot."""
        indlabel = ind.plotlabel()
        # Ensure indlabel is a string
        if not isinstance(indlabel, str):
            indlabel = str(ind.__class__.__name__)
        pstart = 0
        pend = len(xdata)

        for lineidx in range(ind.size()):
            line = ind.lines[lineidx]
            linealias = ind.lines._getlinealias(lineidx)

            # Get plotinfo
            lineplotinfo = getattr(ind.plotlines, linealias, None)
            if lineplotinfo is None:
                lineplotinfo = getattr(ind.plotlines, "_%d" % lineidx, None)

            if lineplotinfo and lineplotinfo._get("_plotskip", False):
                continue

            lplot = list(line.plotrange(pstart, pend))
            if not lplot:
                continue

            # Align data
            plot_xdata = xdata
            if len(lplot) != len(xdata):
                plot_xdata = xdata[: len(lplot)]

            # Find first valid (non-NaN and non-zero-before-real-data) value
            valid_start = 0
            found_nonzero = False
            for i, v in enumerate(lplot):
                if math.isnan(v):
                    continue
                if v != 0.0:
                    valid_start = i
                    found_nonzero = True
                    break

            if not found_nonzero:
                for i in range(len(lplot) - 1):
                    if lplot[i] == 0.0 and lplot[i + 1] != 0.0 and not math.isnan(lplot[i + 1]):
                        valid_start = i + 1
                        found_nonzero = True
                        break

            if valid_start > 0:
                lplot = lplot[valid_start:]
                plot_xdata = plot_xdata[valid_start:]

            if not lplot:
                continue

            # Replace NaN with None for Plotly to skip
            lplot = [None if math.isnan(v) else v for v in lplot]

            # Get color
            color = None
            if lineplotinfo:
                color = lineplotinfo._get("color", None)
            if color is None:
                color = self.p.scheme.color(lineidx)

            label = f"{indlabel} - {linealias}" if ind.size() > 1 else indlabel

            # Determine plot method
            pltmethod = "plot"
            if lineplotinfo:
                pltmethod = lineplotinfo._get("_method", "plot")

            if pltmethod == "bar":
                fig.add_trace(
                    go.Bar(x=plot_xdata, y=lplot, name=label, opacity=0.6),
                    row=row,
                    col=1,
                )
            else:
                fig.add_trace(
                    go.Scatter(
                        x=plot_xdata,
                        y=lplot,
                        mode="lines",
                        name=label,
                        line=dict(color=self._to_plotly_color(color)),
                    ),
                    row=row,
                    col=1,
                )

    def _to_plotly_color(self, color):
        """Convert matplotlib color to plotly color."""
        if color is None:
            return None
        if isinstance(color, str):
            # Handle gray values like "0.75"
            try:
                gray = float(color)
                gray_int = int(gray * 255)
                return f"rgb({gray_int},{gray_int},{gray_int})"
            except ValueError:
                pass
            return color
        if isinstance(color, (tuple, list)):
            if len(color) == 3:
                r, g, b = color
                if all(0 <= c <= 1 for c in color):
                    return f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"
                return f"rgb({r},{g},{b})"
            elif len(color) == 4:
                r, g, b, a = color
                if all(0 <= c <= 1 for c in color):
                    return f"rgba({int(r*255)},{int(g*255)},{int(b*255)},{a})"
                return f"rgba({r},{g},{b},{a})"
        return str(color)

    def _update_layout(self, fig, strategy):
        """Update figure layout with styling."""
        datalabel = ""
        if strategy.datas:
            data = strategy.datas[0]
            if hasattr(data, "_name") and data._name:
                datalabel = data._name

        fig.update_layout(
            title=f"Backtrader Chart - {datalabel}" if datalabel else "Backtrader Chart",
            template=self.p.scheme.plotly_theme,
            height=800,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
            xaxis_rangeslider_visible=self.p.scheme.rangeslider,
        )

        # Disable rangeslider to avoid duplicating the equity/drawdown subplot
        fig.update_xaxes(rangeslider_visible=False)

        if self.p.scheme.rangeslider:
            rangeslider = dict(visible=True)
            if not self.p.scheme.rangeslider_preview:
                rangeslider.update(
                    thickness=0.05,
                    bgcolor="rgba(0,0,0,0)",
                    borderwidth=0,
                    yaxis=dict(rangemode="fixed", range=[1e12, 1e12 + 1]),
                )

            fig.update_xaxes(rangeslider=rangeslider, row=1, col=1)

        # Best-practice: add range selector buttons (bottom axis only)
        try:
            bottom_row = fig._get_subplot_rows_columns()[0][-1]
            fig.update_xaxes(
                rangeselector=dict(
                    buttons=list(
                        [
                            dict(count=1, label="1m", step="month", stepmode="backward"),
                            dict(count=3, label="3m", step="month", stepmode="backward"),
                            dict(count=6, label="6m", step="month", stepmode="backward"),
                            dict(count=1, label="1y", step="year", stepmode="backward"),
                            dict(step="all", label="All"),
                        ]
                    )
                ),
                row=bottom_row,
                col=1,
            )
        except Exception:
            pass

        # Crosshair spike lines
        fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor", spikethickness=1)
        fig.update_yaxes(showspikes=True, spikemode="across", spikesnap="cursor", spikethickness=1)

        # Update y-axes with decimal places format
        tick_format = self._get_tick_format()
        fig.update_yaxes(side="right", tickformat=tick_format)

    def _sortdataindicators(self, strategy):
        """Sort indicators and observers into appropriate lists."""
        self.dplotstop = []
        self.dplotsup = collections.defaultdict(list)
        self.dplotsdown = collections.defaultdict(list)
        self.dplotsover = collections.defaultdict(list)

        # Sort observers
        for x in strategy.getobservers():
            if not x.plotinfo.plot or x.plotinfo.plotskip:
                continue

            if x.plotinfo.subplot:
                self.dplotstop.append(x)
            else:
                key = getattr(x._clock, "owner", x._clock)
                self.dplotsover[key].append(x)

        # Sort indicators
        for x in strategy.getindicators():
            if not hasattr(x, "plotinfo"):
                continue

            if not x.plotinfo.plot or x.plotinfo.plotskip:
                continue

            x._plotinit()

            key = getattr(x._clock, "owner", x._clock)
            if key is strategy:
                key = strategy.data

            if getattr(x.plotinfo, "plotforce", False):
                if key not in strategy.datas:
                    while key not in strategy.datas:
                        key = key._clock

            xpmaster = x.plotinfo.plotmaster
            if xpmaster is x:
                xpmaster = None
            if xpmaster is not None:
                key = xpmaster

            if x.plotinfo.subplot and xpmaster is None:
                if x.plotinfo.plotabove:
                    self.dplotsup[key].append(x)
                else:
                    self.dplotsdown[key].append(x)
            else:
                self.dplotsover[key].append(x)

    def show(self):
        """Display all figures."""
        for fig in self.figs:
            fig.show()

    def savefig(self, fig, filename, width=1600, height=900, scale=2):
        """Save figure to file."""
        if filename.endswith(".html"):
            fig.write_html(filename)
        else:
            fig.write_image(filename, width=width, height=height, scale=scale)

    def _collect_buysell_signals(self, strategy):
        """Collect buy/sell signals from strategy automatically."""
        self.buysell_markers = []

        # Method 1: Try to get from Transactions analyzer (most reliable)
        if hasattr(strategy, "analyzers"):
            for analyzer in strategy.analyzers:
                if analyzer.__class__.__name__ == "Transactions":
                    txn = analyzer.get_analysis()
                    for dt, trades in txn.items():
                        for trade in trades:
                            # trade format: [size, price, value, ...]
                            size = trade[0]
                            price = trade[1]
                            self.buysell_markers.append(
                                {
                                    "datetime": dt,
                                    "price": price,
                                    "type": "buy" if size > 0 else "sell",
                                }
                            )
                    if self.buysell_markers:
                        return

        # Method 2: Try to get from broker's order history
        if hasattr(strategy, "broker") and hasattr(strategy.broker, "orders"):
            for order in strategy.broker.orders:
                if order.status == order.Completed:
                    # Get execution datetime and price
                    exec_dt = num2date(order.executed.dt)
                    self.buysell_markers.append(
                        {
                            "datetime": exec_dt,
                            "price": order.executed.price,
                            "type": "buy" if order.isbuy() else "sell",
                        }
                    )
            if self.buysell_markers:
                return

        # Method 3: Check if strategy has _buysell attribute (user-defined)
        if hasattr(strategy, "_buysell") and strategy._buysell:
            self.buysell_markers = strategy._buysell
            return

        # Method 4: Try to get from BuySell observer
        for obs in strategy.observers:
            if obs.__class__.__name__ == "BuySell":
                buy_line = obs.lines.buy
                sell_line = obs.lines.sell
                buy_vals = list(buy_line.plotrange(0, len(strategy)))
                sell_vals = list(sell_line.plotrange(0, len(strategy)))

                st_dtime = strategy.lines.datetime.plot()
                for i, (bv, sv) in enumerate(zip(buy_vals, sell_vals)):
                    if not math.isnan(bv):
                        self.buysell_markers.append(
                            {"datetime": self._num2date(st_dtime[i]), "price": bv, "type": "buy"}
                        )
                    if not math.isnan(sv):
                        self.buysell_markers.append(
                            {"datetime": self._num2date(st_dtime[i]), "price": sv, "type": "sell"}
                        )
                break

    def _plot_buysell_markers(self, fig, data, xdata, lows, highs, row):
        """Plot buy/sell markers on the price chart with offset from price."""
        if not self.buysell_markers:
            return

        # Calculate price range for offset
        price_range = max(highs) - min(lows) if highs and lows else 1
        offset = price_range * 0.03  # 3% offset from high/low

        # Create datetime to index mapping for finding low/high values
        dt_to_idx = {dt: i for i, dt in enumerate(xdata)}

        buy_x, buy_y, buy_prices = [], [], []
        sell_x, sell_y, sell_prices = [], [], []

        for marker in self.buysell_markers:
            marker_dt = marker["datetime"]
            price = marker["price"]

            # Find the closest datetime in xdata
            idx = dt_to_idx.get(marker_dt)
            if idx is None:
                # Try to find closest match
                for i, dt in enumerate(xdata):
                    if hasattr(dt, "date") and hasattr(marker_dt, "date"):
                        if dt.date() == marker_dt.date():
                            idx = i
                            break

            if idx is not None and idx < len(lows) and idx < len(highs):
                if marker["type"] == "buy":
                    buy_x.append(marker_dt)
                    buy_y.append(lows[idx] - offset)  # Below the low
                    buy_prices.append(price)
                else:
                    sell_x.append(marker_dt)
                    sell_y.append(highs[idx] + offset)  # Above the high
                    sell_prices.append(price)

        # Plot buy markers (triangle up) below lows
        if buy_x:
            fig.add_trace(
                go.Scatter(
                    x=buy_x,
                    y=buy_y,
                    mode="markers",
                    name="Buy",
                    marker=dict(
                        symbol="triangle-up",
                        size=self.p.scheme.buymarker_size,
                        color=self.p.scheme.buymarker_color,
                        line=dict(width=1, color="white"),
                    ),
                    customdata=buy_prices,
                    hovertemplate="Buy @ %{customdata:.2f}<extra></extra>",
                ),
                row=row,
                col=1,
            )

        # Plot sell markers (triangle down) above highs
        if sell_x:
            fig.add_trace(
                go.Scatter(
                    x=sell_x,
                    y=sell_y,
                    mode="markers",
                    name="Sell",
                    marker=dict(
                        symbol="triangle-down",
                        size=self.p.scheme.sellmarker_size,
                        color=self.p.scheme.sellmarker_color,
                        line=dict(width=1, color="white"),
                    ),
                    customdata=sell_prices,
                    hovertemplate="Sell @ %{customdata:.2f}<extra></extra>",
                ),
                row=row,
                col=1,
            )

    def _plot_equity_curve(self, fig, strategy, xdata, pstart, pend, row):
        """Plot equity curve with drawdown area."""
        equity_values = None
        equity_dates = None

        # Method 1: Try to get from TotalValue analyzer (recommended)
        if hasattr(strategy, "analyzers"):
            for analyzer in strategy.analyzers:
                if analyzer.__class__.__name__ == "TotalValue":
                    total_value_data = analyzer.get_analysis()
                    if total_value_data:
                        equity_dates = list(total_value_data.keys())
                        equity_values = list(total_value_data.values())
                        break

        # Method 2: Try to get from Broker observer
        if not equity_values:
            for obs in strategy.observers:
                if obs.__class__.__name__ == "Broker":
                    if hasattr(obs.lines, "value"):
                        equity_values = list(obs.lines.value.plotrange(pstart, pend))
                        equity_dates = xdata
                        break

        if not equity_values or len(equity_values) == 0:
            return row

        # Use equity_dates if available, otherwise use xdata
        plot_xdata = equity_dates if equity_dates else xdata
        plot_equity = equity_values

        # Filter NaN values
        valid_data = [(x, v) for x, v in zip(plot_xdata, plot_equity) if not math.isnan(v)]
        if not valid_data:
            return row

        plot_xdata, plot_equity = zip(*valid_data)
        plot_xdata = list(plot_xdata)
        plot_equity = list(plot_equity)

        # Calculate percentage return from initial
        initial_value = plot_equity[0] if plot_equity[0] != 0 else 1
        pct_equity = [(v / initial_value - 1) * 100 for v in plot_equity]

        # Calculate drawdown
        running_max = plot_equity[0]
        drawdowns = []
        for v in plot_equity:
            if v > running_max:
                running_max = v
            dd = ((v - running_max) / running_max) * 100 if running_max != 0 else 0
            drawdowns.append(dd)

        max_dd = min(drawdowns) if drawdowns else 0

        # Plot drawdown first (as filled area at bottom)
        fig.add_trace(
            go.Scatter(
                x=plot_xdata,
                y=drawdowns,
                mode="lines",
                name=f"Drawdown (Max: {max_dd:.2f}%)",
                line=dict(color="#E74C3C", width=1),
                fill="tozeroy",
                fillcolor="rgba(231, 76, 60, 0.3)",
                hovertemplate="Drawdown: %{y:.2f}%<extra></extra>",
            ),
            row=row,
            col=1,
        )

        # Plot equity curve on top
        fig.add_trace(
            go.Scatter(
                x=plot_xdata,
                y=pct_equity,
                mode="lines",
                name="Return %",
                line=dict(color=self.p.scheme.equity_color, width=2),
                hovertemplate="Return: %{y:.2f}%<extra></extra>",
            ),
            row=row,
            col=1,
        )

        # Add zero line
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=row, col=1)

        return row + 1
