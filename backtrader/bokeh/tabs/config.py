#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Configuration tab.

Displays configuration info for strategy and data.
"""

from ..tab import BokehTab

try:
    from bokeh.models import ColumnDataSource, DataTable, TableColumn
    from bokeh.models.widgets import Div
    from bokeh.layouts import column
    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False


class ConfigTab(BokehTab):
    """Configuration tab.
    
    Displays strategy parameters, data configuration and other info.
    """
    
    def _is_useable(self):
        """Config tab is always useable."""
        return BOKEH_AVAILABLE
    
    def _get_panel(self):
        """Get panel content.
        
        Returns:
            tuple: (widget, title)
        """
        strategy = self.strategy
        scheme = self.scheme
        
        widgets = []
        text_color = scheme.text_color if scheme else '#333'
        
        # Strategy parameters
        if strategy is not None:
            # Strategy name
            strategy_name = strategy.__class__.__name__
            widgets.append(Div(
                text=f'<h3 style="color: {text_color};">Strategy: {strategy_name}</h3>',
                sizing_mode='stretch_width'
            ))
            
            # Strategy parameters
            params = {}
            if hasattr(strategy, 'params'):
                for name in dir(strategy.params):
                    if not name.startswith('_'):
                        try:
                            value = getattr(strategy.params, name)
                            if not callable(value):
                                params[name] = value
                        except Exception:
                            pass
            
            if params:
                source = ColumnDataSource(data={
                    'parameter': list(params.keys()),
                    'value': [str(v) for v in params.values()]
                })
                
                columns = [
                    TableColumn(field='parameter', title='Parameter'),
                    TableColumn(field='value', title='Value'),
                ]
                
                table = DataTable(
                    source=source,
                    columns=columns,
                    width=400,
                    height=min(len(params) * 25 + 30, 300),
                    index_position=None
                )
                widgets.append(table)
            
            # Data source info
            if hasattr(strategy, 'datas') and strategy.datas:
                widgets.append(Div(
                    text=f'<h3 style="color: {text_color};">Data Feeds</h3>',
                    sizing_mode='stretch_width'
                ))
                
                data_info = []
                for i, data in enumerate(strategy.datas):
                    name = data._name if hasattr(data, '_name') else f'Data{i}'
                    length = len(data) if hasattr(data, '__len__') else 'N/A'
                    data_info.append({
                        'name': name,
                        'length': str(length),
                        'timeframe': str(getattr(data._timeframe, 'name', 'N/A') if hasattr(data, '_timeframe') else 'N/A'),
                    })
                
                if data_info:
                    source = ColumnDataSource(data={
                        'name': [d['name'] for d in data_info],
                        'length': [d['length'] for d in data_info],
                        'timeframe': [d['timeframe'] for d in data_info],
                    })
                    
                    columns = [
                        TableColumn(field='name', title='Name'),
                        TableColumn(field='length', title='Length'),
                        TableColumn(field='timeframe', title='Timeframe'),
                    ]
                    
                    table = DataTable(
                        source=source,
                        columns=columns,
                        width=400,
                        height=min(len(data_info) * 25 + 30, 200),
                        index_position=None
                    )
                    widgets.append(table)
        
        if not widgets:
            widgets.append(Div(text='<p>No configuration available</p>'))
        
        content = column(*widgets, sizing_mode='stretch_width')
        return content, 'Config'
