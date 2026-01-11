#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Web 应用服务器

提供 Bokeh Server 的封装
"""

import logging
import webbrowser

try:
    from bokeh.application import Application
    from bokeh.application.handlers import FunctionHandler
    from bokeh.server.server import Server
    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False

_logger = logging.getLogger(__name__)


class Webapp:
    """Web 应用服务器
    
    封装 Bokeh Server，提供以下功能：
    - 自动启动服务器
    - 会话管理
    - 自动打开浏览器
    
    属性:
        title: 页面标题
        template: 模板文件名
        scheme: 主题实例
        address: 服务器地址
        port: 服务器端口
    """
    
    def __init__(self, title, template, scheme, on_root_model, 
                 on_session_destroyed=None, autostart=True, 
                 address='localhost', port=8999):
        """初始化 Web 应用
        
        Args:
            title: 页面标题
            template: 模板文件名
            scheme: 主题实例
            on_root_model: 构建根模型的回调函数
            on_session_destroyed: 会话销毁回调（可选）
            autostart: 是否自动启动
            address: 服务器地址
            port: 服务器端口
        """
        self._title = title
        self._template = template
        self._scheme = scheme
        self._on_root_model = on_root_model
        self._on_session_destroyed = on_session_destroyed
        self._autostart = autostart
        self._address = address
        self._port = port
        self._server = None
    
    def _make_document(self, doc):
        """创建 Bokeh 文档
        
        Args:
            doc: Bokeh 文档实例
        """
        # 设置标题
        doc.title = self._title
        
        # 设置会话销毁回调
        if self._on_session_destroyed is not None:
            doc.on_session_destroyed(self._on_session_destroyed)
        
        # 构建根模型
        root_model = self._on_root_model(doc)
        
        if root_model is not None:
            doc.add_root(root_model)
        
        # 应用主题样式
        if self._scheme is not None:
            self._apply_theme(doc)
    
    def _apply_theme(self, doc):
        """应用主题到文档
        
        Args:
            doc: Bokeh 文档实例
        """
        # 设置背景颜色等样式
        if hasattr(self._scheme, 'body_background_color'):
            # 通过 CSS 设置页面样式
            from bokeh.models import Div
            style_html = f'''
            <style>
                body {{
                    background-color: {self._scheme.body_background_color};
                    color: {getattr(self._scheme, 'text_color', '#333')};
                }}
                .bk-root {{
                    background-color: {self._scheme.body_background_color};
                }}
            </style>
            '''
            style_div = Div(text=style_html, visible=False)
            doc.add_root(style_div)
    
    def start(self, loop=None):
        """启动服务器
        
        Args:
            loop: Tornado IOLoop（可选）
        """
        if not BOKEH_AVAILABLE:
            _logger.error('Bokeh is not available. Cannot start server.')
            return
        
        _logger.info(f'Starting Bokeh server at http://{self._address}:{self._port}')
        
        # 创建应用
        handler = FunctionHandler(self._make_document)
        app = Application(handler)
        
        # 创建服务器
        self._server = Server(
            {'/': app},
            address=self._address,
            port=self._port,
            allow_websocket_origin=[f'{self._address}:{self._port}', 'localhost:' + str(self._port)]
        )
        
        self._server.start()
        
        # 自动打开浏览器
        if self._autostart:
            url = f'http://{self._address}:{self._port}/'
            _logger.info(f'Opening browser at {url}')
            webbrowser.open(url)
        
        # 启动 IOLoop
        if loop is not None:
            loop.start()
        else:
            self._server.io_loop.start()
    
    def stop(self):
        """停止服务器"""
        if self._server is not None:
            self._server.stop()
            _logger.info('Bokeh server stopped')
