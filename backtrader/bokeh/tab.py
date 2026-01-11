#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Tab base class.

Provides extensible tab architecture for creating custom tabs.
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
    """Tab base class.
    
    Abstract base class for creating custom tabs.
    Subclasses must implement _is_useable and _get_panel methods.
    
    Attributes:
        _app: BacktraderBokeh application instance
        _figurepage: Figure page instance
        _client: Client instance (optional, for live mode)
        _panel: Bokeh Panel instance
    
    Example:
        class MyCustomTab(BokehTab):
            def _is_useable(self):
                return True
            
            def _get_panel(self):
                from bokeh.models import Div
                div = Div(text='<h1>My Content</h1>')
                return div, 'My Tab'
    """
    
    def __init__(self, app, figurepage, client=None):
        """Initialize tab.
        
        Args:
            app: BacktraderBokeh application instance
            figurepage: Figure page instance
            client: Client instance (optional)
        """
        self._app = app
        self._figurepage = figurepage
        self._client = client
        self._panel = None
    
    def _is_useable(self):
        """Check if tab is useable.
        
        Subclasses must implement this method.
        
        Returns:
            bool: Whether tab is useable
        """
        raise NotImplementedError('_is_useable needs to be implemented.')
    
    def _get_panel(self):
        """Get tab content.
        
        Subclasses must implement this method.
        
        Returns:
            tuple: (child_widget, title) - Child widget and title
        """
        raise NotImplementedError('_get_panel needs to be implemented.')
    
    def is_useable(self):
        """Public interface: Check if tab is useable.
        
        Returns:
            bool: Whether tab is useable
        """
        return self._is_useable()
    
    def get_panel(self):
        """Public interface: Get Bokeh Panel.
        
        Returns:
            Panel: Bokeh Panel instance
        """
        if not BOKEH_AVAILABLE or Panel is None:
            return None
        child, title = self._get_panel()
        self._panel = Panel(child=child, title=title)
        return self._panel
    
    @property
    def strategy(self):
        """Get strategy instance."""
        if self._figurepage is not None:
            return getattr(self._figurepage, 'strategy', None)
        return None
    
    @property
    def scheme(self):
        """Get theme instance."""
        if self._app is not None:
            return getattr(self._app, 'scheme', None)
        return None
