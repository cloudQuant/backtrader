#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Bokeh 主题基类

定义所有绘图相关的样式参数
"""


class Scheme:
    """Bokeh 绘图主题基类
    
    定义所有绘图相关的样式参数，子类可通过重写 _set_params 方法
    来自定义样式。
    
    属性分类：
    - 颜色配置: barup, bardown, volup, voldown 等
    - 背景配置: background_fill, body_background_color 等
    - 网格配置: grid_line_color 等
    - 文字配置: axis_text_color 等
    - 十字准线: crosshair_line_color 等
    - 图表配置: plot_sizing_mode, plot_height 等
    """
    
    def __init__(self):
        self._set_params()
    
    def _set_params(self):
        """设置默认参数
        
        子类应该先调用 super()._set_params() 然后覆盖特定参数
        """
        # ========== 蜡烛图颜色配置 ==========
        self.barup = '#26a69a'               # 上涨蜡烛颜色
        self.bardown = '#ef5350'             # 下跌蜡烛颜色
        self.barup_wick = '#26a69a'          # 上涨蜡烛影线颜色
        self.bardown_wick = '#ef5350'        # 下跌蜡烛影线颜色
        self.barup_outline = '#26a69a'       # 上涨蜡烛边框颜色
        self.bardown_outline = '#ef5350'     # 下跌蜡烛边框颜色
        
        # ========== 成交量颜色配置 ==========
        self.volup = '#26a69a'               # 上涨成交量颜色
        self.voldown = '#ef5350'             # 下跌成交量颜色
        
        # ========== 背景配置 ==========
        self.background_fill = '#fafafa'     # 图表背景色
        self.body_background_color = '#ffffff'  # 页面背景色
        self.border_fill = '#ffffff'         # 边框填充色
        
        # ========== 网格配置 ==========
        self.grid_line_color = '#e0e0e0'     # 网格线颜色
        
        # ========== 坐标轴配置 ==========
        self.axis_line_color = '#666666'     # 坐标轴线颜色
        self.tick_line_color = '#666666'     # 刻度线颜色
        self.axis_text_color = '#666666'     # 坐标轴文字颜色
        self.axis_label_text_color = '#666666'  # 坐标轴标签颜色
        
        # ========== 标题配置 ==========
        self.plot_title_text_color = '#333333'  # 图表标题颜色
        
        # ========== 图例配置 ==========
        self.legend_background_color = '#ffffff'  # 图例背景色
        self.legend_text_color = '#333333'        # 图例文字颜色
        self.legend_click = 'hide'                # 点击图例行为: 'hide' 或 'mute'
        
        # ========== 十字准线配置 ==========
        self.crosshair_line_color = '#999999'  # 十字准线颜色
        
        # ========== 标签页配置 ==========
        self.tab_active_background_color = '#e0e0e0'  # 活动标签背景色
        self.tab_active_color = '#333333'             # 活动标签文字颜色
        
        # ========== 表格配置 ==========
        self.table_color_even = '#ffffff'     # 表格偶数行颜色
        self.table_color_odd = '#f5f5f5'      # 表格奇数行颜色
        self.table_header_color = '#e0e0e0'   # 表格表头颜色
        
        # ========== 工具提示配置 ==========
        self.tooltip_background_color = '#ffffff'     # 工具提示背景色
        self.tooltip_text_label_color = '#666666'     # 工具提示标签颜色
        self.tooltip_text_value_color = '#333333'     # 工具提示值颜色
        
        # ========== 代码高亮配置 ==========
        self.tag_pre_background_color = '#f5f5f5'  # 代码块背景色
        self.tag_pre_text_color = '#333333'        # 代码块文字颜色
        
        # ========== 文本配置 ==========
        self.text_color = '#333333'           # 通用文字颜色
        
        # ========== 图表布局配置 ==========
        self.plot_sizing_mode = 'stretch_width'  # 图表尺寸模式
        self.plot_height = 400                   # 默认图表高度
        self.plot_height_volume = 150            # 成交量图高度
        self.plot_height_indicator = 200         # 指标图高度
        
        # ========== 工具栏配置 ==========
        self.toolbar_location = 'right'       # 工具栏位置
        
        # ========== 线条样式配置 ==========
        self.line_width = 1.5                 # 默认线宽
        self.line_alpha = 1.0                 # 默认线条透明度
        
        # ========== 标记配置 ==========
        self.marker_size = 8                  # 标记大小
        self.marker_buy_color = '#26a69a'     # 买入标记颜色
        self.marker_sell_color = '#ef5350'    # 卖出标记颜色
        
        # ========== 数据标签配置 ==========
        self.data_label_font_size = '10pt'    # 数据标签字体大小
        
        # ========== 日期格式配置 ==========
        self.date_format = '%Y-%m-%d'         # 日期格式
        self.datetime_format = '%Y-%m-%d %H:%M'  # 日期时间格式
        
        # ========== 轴格式配置 ==========
        self.xaxis_formatter = None           # X轴格式器
        self.yaxis_formatter = None           # Y轴格式器
    
    def get_color(self, name, default=None):
        """获取颜色配置
        
        Args:
            name: 颜色名称
            default: 默认值
            
        Returns:
            颜色值
        """
        return getattr(self, name, default)
    
    def set_color(self, name, value):
        """设置颜色配置
        
        Args:
            name: 颜色名称
            value: 颜色值
        """
        setattr(self, name, value)
    
    def copy(self):
        """创建主题副本
        
        Returns:
            新的主题实例
        """
        new_scheme = self.__class__()
        for attr in dir(self):
            if not attr.startswith('_') and not callable(getattr(self, attr)):
                setattr(new_scheme, attr, getattr(self, attr))
        return new_scheme
