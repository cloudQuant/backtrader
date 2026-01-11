#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Live client.

Manages Bokeh documents and user interactions.
"""

import logging
from functools import partial

try:
    from bokeh.layouts import column, row, layout
    from bokeh.models import Select, Spacer, Tabs, Button
    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False

from .datahandler import LiveDataHandler
from ..utils import get_datanames

_logger = logging.getLogger(__name__)


class LiveClient:
    """Live client.
    
    Provides real-time plotting functionality, including:
    - Data filtering
    - Navigation controls (pause/play/forward/backward)
    - Data updates
    
    Attributes:
        doc: Bokeh document instance
        model: Bokeh root model
        lookback: Historical data retention
        fill_gaps: Whether to fill data gaps
        plotgroup: Plot group for filtering
    """
    
    NAV_BUTTON_WIDTH = 38
    
    def __init__(self, doc, app, strategy, lookback):
        """Initialize live client.
        
        Args:
            doc: Bokeh document instance
            app: BacktraderBokeh application instance
            strategy: Strategy instance
            lookback: Historical data retention
        """
        self._app = app
        self._strategy = strategy
        self._refresh_fnc = None
        self._datahandler = None
        self._figurepage = None
        self._paused = False
        self._filter = ''
        
        # plotgroup for filter
        self.plotgroup = ''
        # amount of candles to plot
        self.lookback = lookback
        # should gaps in data be filled
        self.fill_gaps = False
        # bokeh document for client
        self.doc = doc
        # model is the root model for bokeh and will be set in baseapp
        self.model = None
        
        # append config tab if default tabs should be added
        if hasattr(self._app, 'p') and getattr(self._app.p, 'use_default_tabs', True):
            from ..tabs import LiveTab
            if LiveTab not in self._app.tabs:
                self._app.tabs.append(LiveTab)
        
        # set plotgroup from app params if provided
        if hasattr(self._app, 'p') and hasattr(self._app.p, 'filter'):
            if self._app.p.filter and self._app.p.filter.get('group'):
                self.plotgroup = self._app.p.filter['group']
        
        # create figurepage
        self._figid, self._figurepage = self._app.create_figurepage(
            self._strategy, filldata=False)
        
        # create model
        self.model, self._refresh_fnc = self._createmodel()
        
        # update model with current figurepage
        self.updatemodel()
    
    def _createmodel(self):
        """Create Bokeh model.
        
        Returns:
            tuple: (model, refresh_function)
        """
        if not BOKEH_AVAILABLE:
            return None, None
        
        client = self
        
        def on_select_filter(a, old, new):
            _logger.debug(f'Switching filter to {new}...')
            # ensure datahandler is stopped
            if client._datahandler is not None:
                client._datahandler.stop()
            client._filter = new
            client.updatemodel()
            _logger.debug('Switching filter finished')
        
        def on_click_nav_action():
            if not client._paused:
                client._pause()
            else:
                client._resume()
            refresh()
        
        def on_click_nav_prev(steps=1):
            client._pause()
            client._set_data_by_idx(client._datahandler.get_last_idx() - steps)
            update_nav_buttons()
        
        def on_click_nav_next(steps=1):
            client._pause()
            client._set_data_by_idx(client._datahandler.get_last_idx() + steps)
            update_nav_buttons()
        
        def refresh():
            client.doc.add_next_tick_callback(update_nav_buttons)
        
        def reset_nav_buttons():
            btn_nav_prev.disabled = True
            btn_nav_next.disabled = True
            btn_nav_action.label = '❙❙'
        
        def update_nav_buttons():
            if client._datahandler is None:
                return
            
            last_idx = client._datahandler.get_last_idx()
            last_avail_idx = client._app.get_last_idx(client._figid)
            
            if last_idx < client.lookback:
                btn_nav_prev.disabled = True
                btn_nav_prev_big.disabled = True
            else:
                btn_nav_prev.disabled = False
                btn_nav_prev_big.disabled = False
            
            if last_idx >= last_avail_idx:
                btn_nav_next.disabled = True
                btn_nav_next_big.disabled = True
            else:
                btn_nav_next.disabled = False
                btn_nav_next_big.disabled = False
            
            if client._paused:
                btn_nav_action.label = '▶'
            else:
                btn_nav_action.label = '❙❙'
        
        # filter selection
        datanames = get_datanames(self._strategy)
        options = [('', 'Strategy')]
        for d in datanames:
            options.append(('D' + d, f'Data: {d}'))
        options.append(('G', 'Plot Group'))
        
        self._filter = 'D' + datanames[0] if datanames else ''
        
        select_filter = Select(
            value=self._filter,
            options=options,
            width=200
        )
        select_filter.on_change('value', on_select_filter)
        
        # navigation buttons
        btn_nav_prev = Button(label='❮', width=self.NAV_BUTTON_WIDTH)
        btn_nav_prev.on_click(lambda: on_click_nav_prev(1))
        
        btn_nav_prev_big = Button(label='❮❮', width=self.NAV_BUTTON_WIDTH)
        btn_nav_prev_big.on_click(lambda: on_click_nav_prev(10))
        
        btn_nav_action = Button(label='❙❙', width=self.NAV_BUTTON_WIDTH)
        btn_nav_action.on_click(on_click_nav_action)
        
        btn_nav_next = Button(label='❯', width=self.NAV_BUTTON_WIDTH)
        btn_nav_next.on_click(lambda: on_click_nav_next(1))
        
        btn_nav_next_big = Button(label='❯❯', width=self.NAV_BUTTON_WIDTH)
        btn_nav_next_big.on_click(lambda: on_click_nav_next(10))
        
        # layout
        controls = row(children=[select_filter])
        nav = row(children=[
            btn_nav_prev_big,
            btn_nav_prev,
            btn_nav_action,
            btn_nav_next,
            btn_nav_next_big
        ])
        
        # tabs
        tabs = Tabs(
            tabs=[],
            sizing_mode=self._app.scheme.plot_sizing_mode if hasattr(self._app, 'scheme') else 'stretch_width'
        )
        tabs.name = 'tabs'
        
        # model
        model = layout(
            [
                # app settings, top area
                [column(controls, width_policy='min'),
                 Spacer(),
                 column(nav, width_policy='min')],
                Spacer(height=15),
                # layout for tabs
                [tabs]
            ],
            sizing_mode='stretch_width'
        )
        
        return model, refresh
    
    def updatemodel(self):
        """Update model."""
        if not BOKEH_AVAILABLE or self.doc is None:
            return
        
        self.doc.hold()
        
        # update figurepage with filter
        self._app.update_figurepage(filter=self._get_filter())
        
        # generate panels
        panels = self._app.generate_model_panels()
        
        # add tab panels
        for t in self._app.tabs:
            tab = t(self._app, self._figurepage, self)
            if tab.is_useable():
                panels.append(tab.get_panel())
        
        # set all tabs (filter out None)
        tabs = self._get_tabs()
        if tabs is not None:
            tabs.tabs = [p for p in panels if p is not None]
        
        # create new data handler
        if self._datahandler is not None:
            self._datahandler.stop()
        
        self._datahandler = LiveDataHandler(
            doc=self.doc,
            app=self._app,
            figid=self._figid,
            lookback=self.lookback,
            fill_gaps=self.fill_gaps
        )
        
        # refresh model
        if self._refresh_fnc is not None:
            self._refresh_fnc()
        
        self.doc.unhold()
    
    def _get_filter(self):
        """Get current filter settings.
        
        Returns:
            dict: Filter configuration
        """
        res = {}
        if self._filter.startswith('D'):
            res['dataname'] = self._filter[1:]
        elif self._filter.startswith('G'):
            res['group'] = self.plotgroup
        return res
    
    def _pause(self):
        """Pause data updates."""
        self._paused = True
    
    def _resume(self):
        """Resume data updates."""
        if not self._paused:
            return
        if self._datahandler is not None:
            self._datahandler.update()
        self._paused = False
    
    def _set_data_by_idx(self, idx=None):
        """Set data by index.
        
        Args:
            idx: Data index (optional)
        """
        if idx is not None:
            # Ensure index is within valid range
            last_avail_idx = self._app.get_last_idx(self._figid)
            idx = min(idx, last_avail_idx)
            idx = max(idx, self.lookback - 1)
        
        # Generate data
        df = self._app.generate_data(
            figid=self._figid,
            end=idx,
            back=self.lookback,
            preserveidx=True,
            fill_gaps=self.fill_gaps
        )
        
        if self._datahandler is not None:
            self._datahandler.set(df)
    
    def _get_tabs(self):
        """Get Tabs component.
        
        Returns:
            Tabs instance or None
        """
        if self.model is None:
            return None
        
        # Find component named 'tabs'
        for child in self.model.children:
            if hasattr(child, '__iter__'):
                for item in child:
                    if hasattr(item, 'name') and item.name == 'tabs':
                        return item
                    if isinstance(item, Tabs):
                        return item
        
        return None
    
    def next(self):
        """Receive new data and update.
        
        Called by LivePlotAnalyzer.next()
        """
        if not self._paused and self._datahandler is not None:
            self._datahandler.update()
        
        if self._refresh_fnc is not None:
            self._refresh_fnc()
    
    def stop(self):
        """Stop client."""
        if self._datahandler is not None:
            self._datahandler.stop()
