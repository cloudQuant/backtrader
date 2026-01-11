#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Blackly 黑色主题

适合深色背景的绘图主题
"""

from .scheme import Scheme


class Blackly(Scheme):
    """黑色主题
    
    深色背景，浅色文字，适合夜间使用或深色界面
    """
    
    def _set_params(self):
        super()._set_params()
        
        # ========== 蜡烛图颜色配置 ==========
        self.barup = '#ff9896'               # 上涨蜡烛颜色 (浅红色)
        self.bardown = '#98df8a'             # 下跌蜡烛颜色 (浅绿色)
        self.barup_wick = self.barup
        self.bardown_wick = self.bardown
        self.barup_outline = self.barup
        self.bardown_outline = self.bardown
        
        # ========== 成交量颜色配置 ==========
        self.volup = '#ff9896'
        self.voldown = '#98df8a'
        
        # ========== 背景配置 ==========
        self.background_fill = '#222222'     # 深色图表背景
        self.body_background_color = '#2B2B2B'  # 深色页面背景
        self.border_fill = '#3C3F41'         # 深色边框
        
        # ========== 网格配置 ==========
        self.grid_line_color = '#444444'
        
        # ========== 坐标轴配置 ==========
        self.axis_line_color = 'darkgrey'
        self.tick_line_color = 'darkgrey'
        self.axis_text_color = 'lightgrey'
        self.axis_label_text_color = 'darkgrey'
        
        # ========== 标题配置 ==========
        self.plot_title_text_color = 'darkgrey'
        
        # ========== 图例配置 ==========
        self.legend_background_color = '#3C3F41'
        self.legend_text_color = 'lightgrey'
        self.legend_click = 'hide'
        
        # ========== 十字准线配置 ==========
        self.crosshair_line_color = '#999999'
        
        # ========== 标签页配置 ==========
        self.tab_active_background_color = '#666666'
        self.tab_active_color = '#bbbbbb'
        
        # ========== 表格配置 ==========
        self.table_color_even = '#404040'
        self.table_color_odd = '#333333'
        self.table_header_color = '#707070'
        
        # ========== 工具提示配置 ==========
        self.tooltip_background_color = '#4C4F51'
        self.tooltip_text_label_color = '#848EFF'
        self.tooltip_text_value_color = '#aaaaaa'
        
        # ========== 代码高亮配置 ==========
        self.tag_pre_background_color = '#222222'
        self.tag_pre_text_color = 'lightgrey'
        
        # ========== 文本配置 ==========
        self.text_color = 'lightgrey'
