#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
标签页基类

提供可扩展的标签页架构，用于创建自定义标签页
"""

Panel = None
BOKEH_AVAILABLE = False

try:
    # Bokeh 3.x
    from bokeh.models import TabPanel as Panel
    BOKEH_AVAILABLE = True
except ImportError:
    try:
        # Bokeh 2.x
        from bokeh.models.widgets import Panel
        BOKEH_AVAILABLE = True
    except ImportError:
        try:
            from bokeh.models import Panel
            BOKEH_AVAILABLE = True
        except ImportError:
            pass


class BokehTab:
    """标签页基类
    
    用于创建自定义标签页的抽象基类。
    子类必须实现 _is_useable 和 _get_panel 方法。
    
    属性:
        _app: BacktraderBokeh 应用实例
        _figurepage: 图表页面实例
        _client: 客户端实例（可选，用于实时模式）
        _panel: Bokeh Panel 实例
    
    使用示例:
        class MyCustomTab(BokehTab):
            def _is_useable(self):
                return True
            
            def _get_panel(self):
                from bokeh.models import Div
                div = Div(text='<h1>My Content</h1>')
                return div, 'My Tab'
    """
    
    def __init__(self, app, figurepage, client=None):
        """初始化标签页
        
        Args:
            app: BacktraderBokeh 应用实例
            figurepage: 图表页面实例
            client: 客户端实例（可选）
        """
        self._app = app
        self._figurepage = figurepage
        self._client = client
        self._panel = None
    
    def _is_useable(self):
        """判断标签页是否可用
        
        子类必须实现此方法。
        
        Returns:
            bool: 标签页是否可用
        """
        raise NotImplementedError('_is_useable needs to be implemented.')
    
    def _get_panel(self):
        """获取标签页内容
        
        子类必须实现此方法。
        
        Returns:
            tuple: (child_widget, title) - 子组件和标题
        """
        raise NotImplementedError('_get_panel needs to be implemented.')
    
    def is_useable(self):
        """公共接口：判断标签页是否可用
        
        Returns:
            bool: 标签页是否可用
        """
        return self._is_useable()
    
    def get_panel(self):
        """公共接口：获取 Bokeh Panel
        
        Returns:
            Panel: Bokeh Panel 实例
        """
        if not BOKEH_AVAILABLE or Panel is None:
            return None
        child, title = self._get_panel()
        self._panel = Panel(child=child, title=title)
        return self._panel
    
    @property
    def strategy(self):
        """获取策略实例"""
        if self._figurepage is not None:
            return getattr(self._figurepage, 'strategy', None)
        return None
    
    @property
    def scheme(self):
        """获取主题实例"""
        if self._app is not None:
            return getattr(self._app, 'scheme', None)
        return None
