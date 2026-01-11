#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Tradimo 白色主题

适合浅色背景的绘图主题
"""

from .blackly import Blackly


class Tradimo(Blackly):
    """白色主题
    
    浅色背景，深色文字，适合日间使用或浅色界面
    继承自 Blackly 以保持参数结构一致
    """
    
    def _set_params(self):
        super()._set_params()
        
        dark_text = '#333333'
        
        # ========== 蜡烛图颜色配置 ==========
        self.barup = '#e6550d'               # 上涨蜡烛颜色 (橙色)
        self.bardown = '#31a354'             # 下跌蜡烛颜色 (绿色)
        self.barup_wick = self.barup
        self.bardown_wick = self.bardown
        self.barup_outline = self.barup
        self.bardown_outline = self.bardown
        
        # ========== 成交量颜色配置 ==========
        self.volup = '#ff9896'
        self.voldown = '#98df8a'
        
        # ========== 背景配置 ==========
        self.background_fill = 'white'
        self.body_background_color = 'white'
        self.border_fill = 'white'
        
        # ========== 网格配置 ==========
        self.grid_line_color = '#eeeeee'
        
        # ========== 坐标轴配置 ==========
        self.axis_line_color = '#222222'
        self.tick_line_color = '#222222'
        self.axis_text_color = dark_text
        self.axis_label_text_color = dark_text
        
        # ========== 标题配置 ==========
        self.plot_title_text_color = dark_text
        
        # ========== 图例配置 ==========
        self.legend_background_color = '#f5f5f5'
        self.legend_text_color = dark_text
        self.legend_click = 'hide'
        
        # ========== 十字准线配置 ==========
        self.crosshair_line_color = '#000000'
        
        # ========== 标签页配置 ==========
        self.tab_active_background_color = '#dddddd'
        self.tab_active_color = '#111111'
        
        # ========== 表格配置 ==========
        self.table_color_even = '#fefefe'
        self.table_color_odd = '#eeeeee'
        self.table_header_color = '#cccccc'
        
        # ========== 工具提示配置 ==========
        self.tooltip_background_color = '#f5f5f5'
        self.tooltip_text_label_color = '#848EFF'
        self.tooltip_text_value_color = '#5c5c5c'
        
        # ========== 代码高亮配置 ==========
        self.tag_pre_background_color = '#f5f5f5'
        self.tag_pre_text_color = dark_text
        
        # ========== 文本配置 ==========
        self.text_color = '#222222'
        
        # ========== 特殊配置 ==========
        self.loc = '#265371'  # 位置线颜色
