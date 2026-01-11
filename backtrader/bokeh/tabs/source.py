#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
源码标签页

显示策略源代码
"""

import inspect
from ..tab import BokehTab

try:
    from bokeh.models.widgets import Div, PreText
    from bokeh.layouts import column
    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False


class SourceTab(BokehTab):
    """源码标签页
    
    显示策略的 Python 源代码。
    """
    
    def _is_useable(self):
        """当有策略时可用"""
        if not BOKEH_AVAILABLE:
            return False
        return self.strategy is not None
    
    def _get_panel(self):
        """获取面板内容
        
        Returns:
            tuple: (widget, title)
        """
        strategy = self.strategy
        scheme = self.scheme
        
        widgets = []
        
        # 获取主题颜色
        bg_color = scheme.tag_pre_background_color if scheme else '#f5f5f5'
        text_color = scheme.tag_pre_text_color if scheme else '#333'
        title_color = scheme.text_color if scheme else '#333'
        
        # 标题
        widgets.append(Div(
            text=f'<h3 style="color: {title_color};">Strategy Source Code</h3>',
            sizing_mode='stretch_width'
        ))
        
        # 获取源代码
        try:
            source_code = inspect.getsource(strategy.__class__)
        except (TypeError, OSError):
            source_code = '# Source code not available'
        
        # 创建源码显示组件
        source_pre = PreText(
            text=source_code,
            width=800,
            height=500,
        )
        widgets.append(source_pre)
        
        content = column(*widgets, sizing_mode='stretch_width')
        return content, 'Source'
