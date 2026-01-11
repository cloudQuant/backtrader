#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""\nLive configuration tab.\n\nFor configuration adjustments in live plotting mode.\n"""

from ..tab import BokehTab

try:
    from bokeh.models.widgets import Div, Slider, Select, Button
    from bokeh.layouts import column, row
    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False


class LiveTab(BokehTab):
    """Live configuration tab.
    
    Provides configuration options for live plotting mode:
    - Lookback adjustment
    - Auto-refresh interval
    - Filter options
    """
    
    def _is_useable(self):
        """Useable in live mode."""
        if not BOKEH_AVAILABLE:
            return False
        return self._client is not None
    
    def _get_panel(self):
        """Get panel content.
        
        Returns:
            tuple: (widget, title)
        """
        scheme = self.scheme
        text_color = scheme.text_color if scheme else '#333'
        
        widgets = []
        
        # Title
        widgets.append(Div(
            text=f'<h3 style="color: {text_color};">Live Plot Settings</h3>',
            sizing_mode='stretch_width'
        ))
        
        # Lookback settings
        lookback_value = getattr(self._client, 'lookback', 100) if self._client else 100
        lookback_slider = Slider(
            start=10,
            end=500,
            value=lookback_value,
            step=10,
            title='Lookback (candles)',
            width=300
        )
        
        def on_lookback_change(attr, old, new):
            if self._client is not None:
                self._client.lookback = new
        
        lookback_slider.on_change('value', on_lookback_change)
        widgets.append(lookback_slider)
        
        # Fill Gaps option
        fill_gaps = getattr(self._client, 'fill_gaps', False) if self._client else False
        fill_gaps_select = Select(
            title='Fill Gaps',
            value='Yes' if fill_gaps else 'No',
            options=['Yes', 'No'],
            width=150
        )
        
        def on_fill_gaps_change(attr, old, new):
            if self._client is not None:
                self._client.fill_gaps = (new == 'Yes')
        
        fill_gaps_select.on_change('value', on_fill_gaps_change)
        widgets.append(fill_gaps_select)
        
        # Plot Group settings
        plotgroup = getattr(self._client, 'plotgroup', '') if self._client else ''
        plotgroup_select = Select(
            title='Plot Group',
            value=plotgroup or 'All',
            options=['All'],  # Can dynamically add more options
            width=200
        )
        widgets.append(plotgroup_select)
        
        # Refresh button
        refresh_btn = Button(label='Refresh', button_type='primary', width=100)
        
        def on_refresh_click():
            if self._client is not None:
                self._client.updatemodel()
        
        refresh_btn.on_click(on_refresh_click)
        widgets.append(refresh_btn)
        
        # Status info
        status_text = 'Running' if self._client and not getattr(self._client, '_paused', True) else 'Paused'
        status_div = Div(
            text=f'<p style="color: {text_color};">Status: <strong>{status_text}</strong></p>',
            sizing_mode='stretch_width'
        )
        widgets.append(status_div)
        
        content = column(*widgets, sizing_mode='stretch_width')
        return content, 'Live'
