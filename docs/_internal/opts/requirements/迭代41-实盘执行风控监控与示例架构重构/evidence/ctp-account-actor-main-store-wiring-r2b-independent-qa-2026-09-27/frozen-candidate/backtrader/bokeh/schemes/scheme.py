#!/usr/bin/env python
"""Bokeh theme base class.

Defines all plotting-related style parameters.
"""


class Scheme:
    """Bokeh plotting theme base class.

    Defines all plotting-related style parameters. Subclasses can customize
    styles by overriding the _set_params method.

    Attribute categories:
    - Color configuration: barup, bardown, volup, voldown, etc.
    - Background configuration: background_fill, body_background_color, etc.
    - Grid configuration: grid_line_color, etc.
    - Text configuration: axis_text_color, etc.
    - Crosshair: crosshair_line_color, etc.
    - Chart configuration: plot_sizing_mode, plot_height, etc.
    """

    def __init__(self):
        """Initialize the scheme with default parameters."""
        self._set_params()

    def _set_params(self):
        """Set default parameters.

        Subclasses should call super()._set_params() first, then override specific parameters.
        """
        # ========== Candlestick color configuration ==========
        self.barup = "#26a69a"  # Up candle color
        self.bardown = "#ef5350"  # Down candle color
        self.barup_wick = "#26a69a"  # Up candle wick color
        self.bardown_wick = "#ef5350"  # Down candle wick color
        self.barup_outline = "#26a69a"  # Up candle outline color
        self.bardown_outline = "#ef5350"  # Down candle outline color

        # ========== Volume color configuration ==========
        self.volup = "#26a69a"  # Up volume color
        self.voldown = "#ef5350"  # Down volume color

        # ========== Background configuration ==========
        self.background_fill = "#fafafa"  # Chart background color
        self.body_background_color = "#ffffff"  # Page background color
        self.border_fill = "#ffffff"  # Border fill color

        # ========== Grid configuration ==========
        self.grid_line_color = "#e0e0e0"  # Grid line color

        # ========== Axis configuration ==========
        self.axis_line_color = "#666666"  # Axis line color
        self.tick_line_color = "#666666"  # Tick line color
        self.axis_text_color = "#666666"  # Axis text color
        self.axis_label_text_color = "#666666"  # Axis label color

        # ========== Title configuration ==========
        self.plot_title_text_color = "#333333"  # Chart title color

        # ========== Legend configuration ==========
        self.legend_background_color = "#ffffff"  # Legend background color
        self.legend_text_color = "#333333"  # Legend text color
        self.legend_click = "hide"  # Legend click behavior: 'hide' or 'mute'

        # ========== Crosshair configuration ==========
        self.crosshair_line_color = "#999999"  # Crosshair line color

        # ========== Tab configuration ==========
        self.tab_active_background_color = "#e0e0e0"  # Active tab background color
        self.tab_active_color = "#333333"  # Active tab text color

        # ========== Table configuration ==========
        self.table_color_even = "#ffffff"  # Table even row color
        self.table_color_odd = "#f5f5f5"  # Table odd row color
        self.table_header_color = "#e0e0e0"  # Table header color

        # ========== Tooltip configuration ==========
        self.tooltip_background_color = "#ffffff"  # Tooltip background color
        self.tooltip_text_label_color = "#666666"  # Tooltip label color
        self.tooltip_text_value_color = "#333333"  # Tooltip value color

        # ========== Code highlight configuration ==========
        self.tag_pre_background_color = "#f5f5f5"  # Code block background color
        self.tag_pre_text_color = "#333333"  # Code block text color

        # ========== Text configuration ==========
        self.text_color = "#333333"  # General text color

        # ========== Chart layout configuration ==========
        self.plot_sizing_mode = "stretch_width"  # Chart sizing mode
        self.plot_height = 400  # Default chart height
        self.plot_height_volume = 150  # Volume chart height
        self.plot_height_indicator = 200  # Indicator chart height

        # ========== Toolbar configuration ==========
        self.toolbar_location = "right"  # Toolbar location

        # ========== Line style configuration ==========
        self.line_width = 1.5  # Default line width
        self.line_alpha = 1.0  # Default line alpha

        # ========== Marker configuration ==========
        self.marker_size = 8  # Marker size
        self.marker_buy_color = "#26a69a"  # Buy marker color
        self.marker_sell_color = "#ef5350"  # Sell marker color

        # ========== Data label configuration ==========
        self.data_label_font_size = "10pt"  # Data label font size

        # ========== Date format configuration ==========
        self.date_format = "%Y-%m-%d"  # Date format
        self.datetime_format = "%Y-%m-%d %H:%M"  # Datetime format

        # ========== Axis format configuration ==========
        self.xaxis_formatter = None  # X-axis formatter
        self.yaxis_formatter = None  # Y-axis formatter

    def get_color(self, name, default=None):
        """Get color configuration.

        Args:
            name: Color name
            default: Default value

        Returns:
            Color value
        """
        return getattr(self, name, default)

    def set_color(self, name, value):
        """Set color configuration.

        Args:
            name: Color name
            value: Color value
        """
        setattr(self, name, value)

    def copy(self):
        """Create a copy of the theme.

        Returns:
            New theme instance
        """
        new_scheme = self.__class__()
        for attr in dir(self):
            if not attr.startswith("_") and not callable(getattr(self, attr)):
                setattr(new_scheme, attr, getattr(self, attr))
        return new_scheme
