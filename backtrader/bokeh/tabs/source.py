#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Source code tab.

Displays strategy source code.
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
    """Source code tab.
    
    Displays the strategy's Python source code.
    """
    
    def _is_useable(self):
        """Useable when strategy exists."""
        if not BOKEH_AVAILABLE:
            return False
        return self.strategy is not None
    
    def _get_panel(self):
        """Get panel content.
        
        Returns:
            tuple: (widget, title)
        """
        strategy = self.strategy
        scheme = self.scheme
        
        widgets = []
        
        # Get theme colors
        bg_color = scheme.tag_pre_background_color if scheme else '#f5f5f5'
        text_color = scheme.tag_pre_text_color if scheme else '#333'
        title_color = scheme.text_color if scheme else '#333'
        
        # Title
        widgets.append(Div(
            text=f'<h3 style="color: {title_color};">Strategy Source Code</h3>',
            sizing_mode='stretch_width'
        ))
        
        # Get source code
        try:
            source_code = inspect.getsource(strategy.__class__)
        except (TypeError, OSError):
            source_code = '# Source code not available'
        
        # Create source code display component
        source_pre = PreText(
            text=source_code,
            width=800,
            height=500,
        )
        widgets.append(source_pre)
        
        content = column(*widgets, sizing_mode='stretch_width')
        return content, 'Source'
