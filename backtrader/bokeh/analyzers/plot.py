#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
实时绘图分析器

提供基于 Bokeh Server 的实时绘图功能
"""

import asyncio
import logging
import threading
from threading import Lock

try:
    import tornado.ioloop
    TORNADO_AVAILABLE = True
except ImportError:
    TORNADO_AVAILABLE = False

import backtrader as bt

from ..app import BacktraderBokeh
from ..webapp import Webapp
from ..schemes import Tradimo, Blackly
from ..live.client import LiveClient

_logger = logging.getLogger(__name__)


class LivePlotAnalyzer(bt.Analyzer):
    """实时绘图分析器
    
    提供基于 Bokeh Server 的实时绘图功能，包括：
    - WebSocket 实时数据推送
    - 暂停/继续功能
    - 前进/后退导航
    - 数据 lookback 控制
    
    参数:
        scheme: 主题实例，默认使用 Tradimo
        style: 图表样式，'bar' 或 'candle'
        lookback: 历史数据保留量
        address: 服务器地址
        port: 服务器端口
        title: 标题
        autostart: 是否自动启动服务器
    
    使用示例:
        cerebro.addanalyzer(LivePlotAnalyzer,
                          scheme=Blackly(),
                          lookback=100,
                          port=8999)
    """
    
    params = (
        ('scheme', None),           # 主题
        ('style', 'bar'),           # 图表样式
        ('lookback', 100),          # 历史数据保留量
        ('address', 'localhost'),   # 服务器地址
        ('port', 8999),             # 服务器端口
        ('title', None),            # 标题
        ('autostart', True),        # 自动启动
    )
    
    def __init__(self, **kwargs):
        super().__init__()
        
        # 设置标题
        title = self.p.title
        if title is None:
            title = f'Live {type(self.strategy).__name__}'
        
        # 设置自动启动
        autostart = kwargs.get('autostart', self.p.autostart)
        
        # 获取主题
        scheme = self.p.scheme
        if scheme is None:
            scheme = Tradimo()
        
        # 创建 Webapp
        self._webapp = Webapp(
            title=title,
            template='basic.html.j2',
            scheme=scheme,
            on_root_model=self._app_cb_build_root_model,
            on_session_destroyed=self._on_session_destroyed,
            autostart=autostart,
            address=self.p.address,
            port=self.p.port
        )
        
        self._lock = Lock()
        self._clients = {}
        self._app_kwargs = kwargs
    
    def _create_app(self):
        """创建 BacktraderBokeh 应用实例
        
        Returns:
            BacktraderBokeh 实例
        """
        return BacktraderBokeh(
            style=self.p.style,
            scheme=self.p.scheme or Tradimo(),
            **self._app_kwargs
        )
    
    def _on_session_destroyed(self, session_context):
        """会话销毁回调
        
        Args:
            session_context: Bokeh 会话上下文
        """
        with self._lock:
            session_id = session_context.id
            if session_id in self._clients:
                self._clients[session_id].stop()
                del self._clients[session_id]
    
    def _t_server(self):
        """服务器线程方法"""
        if not TORNADO_AVAILABLE:
            _logger.error('Tornado is not available. Cannot start Bokeh server.')
            return
        
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = tornado.ioloop.IOLoop.current()
        self._webapp.start(loop)
    
    def _app_cb_build_root_model(self, doc):
        """构建根模型回调
        
        Args:
            doc: Bokeh 文档
            
        Returns:
            根模型
        """
        client = LiveClient(
            doc,
            self._create_app(),
            self.strategy,
            self.p.lookback
        )
        
        with self._lock:
            self._clients[doc.session_context.id] = client
        
        return client.model
    
    def start(self):
        """从 backtrader 启动
        
        启动 Bokeh Server
        """
        _logger.debug('Starting LivePlotAnalyzer...')
        
        t = threading.Thread(target=self._t_server)
        t.daemon = True
        t.start()
    
    def stop(self):
        """从 backtrader 停止"""
        _logger.debug('Stopping LivePlotAnalyzer...')
        
        with self._lock:
            for client in self._clients.values():
                client.stop()
    
    def next(self):
        """从 backtrader 接收新数据
        
        更新所有连接的客户端
        """
        with self._lock:
            for client in self._clients.values():
                client.next()
    
    def get_analysis(self):
        """返回分析结果
        
        Returns:
            dict: 空字典（此分析器用于绘图，不产生分析数据）
        """
        return {}
