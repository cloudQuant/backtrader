#!/usr/bin/env python
"""
Tradimo light theme.

Plotting theme suitable for light backgrounds.
"""

from .blackly import Blackly


class Tradimo(Blackly):
    """Light theme.

    Light background with dark text, suitable for daytime use or light interfaces.
    Inherits from Blackly to maintain consistent parameter structure.
    """

    def _set_params(self):
        super()._set_params()

        dark_text = "#333333"

        # ========== Candlestick color configuration ==========
        self.barup = "#e6550d"  # Up candle color (orange)
        self.bardown = "#31a354"  # Down candle color (green)
        self.barup_wick = self.barup
        self.bardown_wick = self.bardown
        self.barup_outline = self.barup
        self.bardown_outline = self.bardown

        # ========== Volume color configuration ==========
        self.volup = "#ff9896"
        self.voldown = "#98df8a"

        # ========== Background configuration ==========
        self.background_fill = "white"
        self.body_background_color = "white"
        self.border_fill = "white"

        # ========== Grid configuration ==========
        self.grid_line_color = "#eeeeee"

        # ========== Axis configuration ==========
        self.axis_line_color = "#222222"
        self.tick_line_color = "#222222"
        self.axis_text_color = dark_text
        self.axis_label_text_color = dark_text

        # ========== Title configuration ==========
        self.plot_title_text_color = dark_text

        # ========== Legend configuration ==========
        self.legend_background_color = "#f5f5f5"
        self.legend_text_color = dark_text
        self.legend_click = "hide"

        # ========== Crosshair configuration ==========
        self.crosshair_line_color = "#000000"

        # ========== Tab configuration ==========
        self.tab_active_background_color = "#dddddd"
        self.tab_active_color = "#111111"

        # ========== Table configuration ==========
        self.table_color_even = "#fefefe"
        self.table_color_odd = "#eeeeee"
        self.table_header_color = "#cccccc"

        # ========== Tooltip configuration ==========
        self.tooltip_background_color = "#f5f5f5"
        self.tooltip_text_label_color = "#848EFF"
        self.tooltip_text_value_color = "#5c5c5c"

        # ========== Code highlighting configuration ==========
        self.tag_pre_background_color = "#f5f5f5"
        self.tag_pre_text_color = dark_text

        # ========== Text configuration ==========
        self.text_color = "#222222"

        # ========== Special configuration ==========
        self.loc = "#265371"  # Location line color
