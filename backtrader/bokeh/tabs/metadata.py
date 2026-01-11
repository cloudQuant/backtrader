#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Metadata tab.

Displays metadata info for strategy and backtest.
"""

import datetime
from ..tab import BokehTab

try:
    from bokeh.models import ColumnDataSource, DataTable, TableColumn
    from bokeh.models.widgets import Div
    from bokeh.layouts import column
    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False


class MetadataTab(BokehTab):
    """Metadata tab.
    
    Displays metadata info for strategy, data, indicators, etc.
    """
    
    def _is_useable(self):
        """Metadata tab is always useable."""
        return BOKEH_AVAILABLE
    
    def _get_panel(self):
        """Get panel content.
        
        Returns:
            tuple: (widget, title)
        """
        strategy = self.strategy
        scheme = self.scheme
        text_color = scheme.text_color if scheme else '#333'
        
        widgets = []
        
        # Basic info
        widgets.append(Div(
            text=f'<h3 style="color: {text_color};">Backtest Metadata</h3>',
            sizing_mode='stretch_width'
        ))
        
        metadata = {}
        
        # Time info
        metadata['Generated'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if strategy is not None:
            # Strategy info
            metadata['Strategy'] = strategy.__class__.__name__
            
            # Data info
            if hasattr(strategy, 'datas') and strategy.datas:
                metadata['Data Feeds'] = len(strategy.datas)
                
                # Data range
                data = strategy.datas[0]
                if hasattr(data, 'datetime') and len(data) > 0:
                    try:
                        # Get start and end dates
                        start_dt = data.datetime.date(0)
                        if hasattr(data.datetime, 'date'):
                            end_dt = data.datetime.date(-1) if len(data) > 1 else start_dt
                        else:
                            end_dt = start_dt
                        metadata['Start Date'] = str(start_dt)
                        metadata['End Date'] = str(end_dt)
                        metadata['Total Bars'] = len(data)
                    except Exception:
                        pass
            
            # Indicator info
            if hasattr(strategy, '_lineiterators'):
                ind_count = len(strategy._lineiterators.get(1, []))  # IndType = 1
                obs_count = len(strategy._lineiterators.get(2, []))  # ObsType = 2
                metadata['Indicators'] = ind_count
                metadata['Observers'] = obs_count
            
            # Analyzer info
            if hasattr(strategy, 'analyzers'):
                metadata['Analyzers'] = len(strategy.analyzers)
            
            # Broker info
            if hasattr(strategy, 'broker'):
                broker = strategy.broker
                try:
                    metadata['Final Value'] = f'{broker.getvalue():.2f}'
                    metadata['Final Cash'] = f'{broker.getcash():.2f}'
                except Exception:
                    pass
        
        # Create table
        if metadata:
            source = ColumnDataSource(data={
                'property': list(metadata.keys()),
                'value': [str(v) for v in metadata.values()]
            })
            
            columns = [
                TableColumn(field='property', title='Property'),
                TableColumn(field='value', title='Value'),
            ]
            
            table = DataTable(
                source=source,
                columns=columns,
                width=400,
                height=min(len(metadata) * 25 + 30, 400),
                index_position=None
            )
            widgets.append(table)
        
        # Indicator list
        if strategy is not None and hasattr(strategy, '_lineiterators'):
            indicators = strategy._lineiterators.get(1, [])
            if indicators:
                widgets.append(Div(
                    text=f'<h3 style="color: {text_color};">Indicators</h3>',
                    sizing_mode='stretch_width'
                ))
                
                ind_data = []
                for ind in indicators:
                    ind_data.append({
                        'name': ind.__class__.__name__,
                        'lines': ', '.join(getattr(ind.lines, '_getlinealiases', lambda: [])()),
                    })
                
                if ind_data:
                    source = ColumnDataSource(data={
                        'name': [d['name'] for d in ind_data],
                        'lines': [d['lines'] for d in ind_data],
                    })
                    
                    columns = [
                        TableColumn(field='name', title='Indicator'),
                        TableColumn(field='lines', title='Lines'),
                    ]
                    
                    table = DataTable(
                        source=source,
                        columns=columns,
                        width=400,
                        height=min(len(ind_data) * 25 + 30, 200),
                        index_position=None
                    )
                    widgets.append(table)
        
        content = column(*widgets, sizing_mode='stretch_width')
        return content, 'Metadata'
