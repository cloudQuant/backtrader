#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Live plotting analyzer.

Provides real-time plotting functionality based on Bokeh Server.
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
    """Live plotting analyzer.

    Provides real-time plotting functionality based on Bokeh Server, including:
    - WebSocket real-time data push
    - Pause/resume functionality
    - Forward/backward navigation
    - Data lookback control

    Args:
        scheme: Theme instance, defaults to Tradimo
        style: Chart style, 'bar' or 'candle'
        lookback: Amount of historical data to retain
        address: Server address
        port: Server port
        title: Title
        autostart: Whether to auto-start the server

    Example:
        cerebro.addanalyzer(LivePlotAnalyzer,
                          scheme=Blackly(),
                          lookback=100,
                          port=8999)
    """
    
    params = (
        ('scheme', None),           # Theme
        ('style', 'bar'),           # Chart style
        ('lookback', 100),          # Historical data retention
        ('address', 'localhost'),   # Server address
        ('port', 8999),             # Server port
        ('title', None),            # Title
        ('autostart', True),        # Auto-start
    )
    
    def __init__(self, **kwargs):
        super().__init__()
        
        # Set title
        title = self.p.title
        if title is None:
            title = f'Live {type(self.strategy).__name__}'
        
        # Set auto-start
        autostart = kwargs.get('autostart', self.p.autostart)
        
        # Get theme
        scheme = self.p.scheme
        if scheme is None:
            scheme = Tradimo()
        
        # Create Webapp
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
        """Create BacktraderBokeh application instance.

        Returns:
            BacktraderBokeh instance
        """
        return BacktraderBokeh(
            style=self.p.style,
            scheme=self.p.scheme or Tradimo(),
            **self._app_kwargs
        )
    
    def _on_session_destroyed(self, session_context):
        """Session destroyed callback.

        Args:
            session_context: Bokeh session context
        """
        with self._lock:
            session_id = session_context.id
            if session_id in self._clients:
                self._clients[session_id].stop()
                del self._clients[session_id]
    
    def _t_server(self):
        """Server thread method."""
        if not TORNADO_AVAILABLE:
            _logger.error('Tornado is not available. Cannot start Bokeh server.')
            return
        
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = tornado.ioloop.IOLoop.current()
        self._webapp.start(loop)
    
    def _app_cb_build_root_model(self, doc):
        """Build root model callback.

        Args:
            doc: Bokeh document

        Returns:
            Root model
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
        """Start from backtrader.

        Starts the Bokeh Server.
        """
        _logger.debug('Starting LivePlotAnalyzer...')
        
        t = threading.Thread(target=self._t_server)
        t.daemon = True
        t.start()
    
    def stop(self):
        """Stop from backtrader."""
        _logger.debug('Stopping LivePlotAnalyzer...')
        
        with self._lock:
            for client in self._clients.values():
                client.stop()
    
    def next(self):
        """Receive new data from backtrader.

        Updates all connected clients.
        """
        with self._lock:
            for client in self._clients.values():
                client.next()
    
    def get_analysis(self):
        """Return analysis results.

        Returns:
            dict: Empty dict (this analyzer is for plotting, does not produce analysis data)
        """
        return {}
