#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Blackly dark theme.

Plotting theme suitable for dark backgrounds.
"""

from .scheme import Scheme


class Blackly(Scheme):
    """Dark theme.
    
    Dark background with light text, suitable for night use or dark interfaces.
    """
    
    def _set_params(self):
        super()._set_params()
        
        # ========== Candlestick color configuration ==========
        self.barup = '#ff9896'               # Up candle color (light red)
        self.bardown = '#98df8a'             # Down candle color (light green)
        self.barup_wick = self.barup
        self.bardown_wick = self.bardown
        self.barup_outline = self.barup
        self.bardown_outline = self.bardown
        
        # ========== Volume color configuration ==========
        self.volup = '#ff9896'
        self.voldown = '#98df8a'
        
        # ========== Background configuration ==========
        self.background_fill = '#222222'     # Dark chart background
        self.body_background_color = '#2B2B2B'  # Dark page background
        self.border_fill = '#3C3F41'         # Dark border
        
        # ========== Grid configuration ==========
        self.grid_line_color = '#444444'
        
        # ========== Axis configuration ==========
        self.axis_line_color = 'darkgrey'
        self.tick_line_color = 'darkgrey'
        self.axis_text_color = 'lightgrey'
        self.axis_label_text_color = 'darkgrey'
        
        # ========== Title configuration ==========
        self.plot_title_text_color = 'darkgrey'
        
        # ========== Legend configuration ==========
        self.legend_background_color = '#3C3F41'
        self.legend_text_color = 'lightgrey'
        self.legend_click = 'hide'
        
        # ========== Crosshair configuration ==========
        self.crosshair_line_color = '#999999'
        
        # ========== Tab configuration ==========
        self.tab_active_background_color = '#666666'
        self.tab_active_color = '#bbbbbb'
        
        # ========== Table configuration ==========
        self.table_color_even = '#404040'
        self.table_color_odd = '#333333'
        self.table_header_color = '#707070'
        
        # ========== Tooltip configuration ==========
        self.tooltip_background_color = '#4C4F51'
        self.tooltip_text_label_color = '#848EFF'
        self.tooltip_text_value_color = '#aaaaaa'
        
        # ========== Code highlighting configuration ==========
        self.tag_pre_background_color = '#222222'
        self.tag_pre_text_color = 'lightgrey'
        
        # ========== Text configuration ==========
        self.text_color = 'lightgrey'
