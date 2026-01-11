#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Web application server.

Provides Bokeh Server wrapper."""

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
    """Web application server.

    Wraps Bokeh Server, providing the following features:
    - Auto-start server
    - Session management
    - Auto-open browser

    Attributes:
        title: Page title
        template: Template filename
        scheme: Theme instance
        address: Server address
        port: Server port
    """
    
    def __init__(self, title, template, scheme, on_root_model, 
                 on_session_destroyed=None, autostart=True, 
                 address='localhost', port=8999):
        """Initialize web application.

        Args:
            title: Page title
            template: Template filename
            scheme: Theme instance
            on_root_model: Callback function to build root model
            on_session_destroyed: Session destroyed callback (optional)
            autostart: Whether to auto-start
            address: Server address
            port: Server port
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
        """Create Bokeh document.

        Args:
            doc: Bokeh document instance
        """
        # Set title
        doc.title = self._title
        
        # Set session destroyed callback
        if self._on_session_destroyed is not None:
            doc.on_session_destroyed(self._on_session_destroyed)
        
        # Build root model
        root_model = self._on_root_model(doc)
        
        if root_model is not None:
            doc.add_root(root_model)
        
        # Apply theme styles
        if self._scheme is not None:
            self._apply_theme(doc)
    
    def _apply_theme(self, doc):
        """Apply theme to document.

        Args:
            doc: Bokeh document instance
        """
        # Set background color and other styles
        if hasattr(self._scheme, 'body_background_color'):
            # Set page styles via CSS
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
        """Start server.

        Args:
            loop: Tornado IOLoop (optional)
        """
        if not BOKEH_AVAILABLE:
            _logger.error('Bokeh is not available. Cannot start server.')
            return
        
        _logger.info(f'Starting Bokeh server at http://{self._address}:{self._port}')
        
        # Create application
        handler = FunctionHandler(self._make_document)
        app = Application(handler)
        
        # Create server
        self._server = Server(
            {'/': app},
            address=self._address,
            port=self._port,
            allow_websocket_origin=[f'{self._address}:{self._port}', 'localhost:' + str(self._port)]
        )
        
        self._server.start()
        
        # Auto-open browser
        if self._autostart:
            url = f'http://{self._address}:{self._port}/'
            _logger.info(f'Opening browser at {url}')
            webbrowser.open(url)
        
        # Start IOLoop
        if loop is not None:
            loop.start()
        else:
            self._server.io_loop.start()
    
    def stop(self):
        """Stop server."""
        if self._server is not None:
            self._server.stop()
            _logger.info('Bokeh server stopped')
