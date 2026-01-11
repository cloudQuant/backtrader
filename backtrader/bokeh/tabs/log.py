#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Log tab.

Displays strategy execution logs.
"""

import logging
from collections import deque
from ..tab import BokehTab

try:
    from bokeh.models import ColumnDataSource, DataTable, TableColumn
    from bokeh.models.widgets import Div
    from bokeh.layouts import column
    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False

# Global log storage
_log_storage = {}


class LogHandler(logging.Handler):
    """Log handler.

    Captures log messages and stores them in specified storage.
    """

    def __init__(self, storage_key, max_records=1000):
        """Initialize log handler.

        Args:
            storage_key: Key to identify log storage in global dictionary.
            max_records: Maximum number of log records to keep (default: 1000).
        """
        super().__init__()
        self.storage_key = storage_key
        self.max_records = max_records
        if storage_key not in _log_storage:
            _log_storage[storage_key] = deque(maxlen=max_records)

    def emit(self, record):
        """Emit a log record.

        Args:
            record: Log record to process.
        """
        log_entry = {
            'time': self.format(record).split(' - ')[0] if ' - ' in self.format(record) else '',
            'level': record.levelname,
            'message': record.getMessage()
        }
        _log_storage[self.storage_key].append(log_entry)


def getlogger(name='backtrader', col=None):
    """Get logger with log handler.
    
    Args:
        name: Logger name
        col: Custom columns (optional)
        
    Returns:
        logging.Logger instance
    """
    logger = logging.getLogger(name)
    
    # Check if LogHandler already added
    has_handler = any(isinstance(h, LogHandler) for h in logger.handlers)
    if not has_handler:
        handler = LogHandler(name)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
    
    return logger


class LogTab(BokehTab):
    """Log tab.
    
    Displays log information during strategy execution.
    
    Attributes:
        cols: Column configuration for display
    """
    
    cols = ['Time', 'Level', 'Message']  # Default columns

    def __init__(self, app, figurepage, client=None, cols=None):
        """Initialize log tab.

        Args:
            app: Bokeh application instance.
            figurepage: Figure page instance.
            client: Optional client instance.
            cols: Custom column configuration for log display.
        """
        super().__init__(app, figurepage, client)
        if cols is not None:
            self.cols = cols
    
    def _is_useable(self):
        """Log tab is always useable."""
        return BOKEH_AVAILABLE
    
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
            text=f'<h3 style="color: {text_color};">Log Messages</h3>',
            sizing_mode='stretch_width'
        ))
        
        # Get log data
        log_data = self._get_log_data()
        
        if log_data:
            # Create data source
            source = ColumnDataSource(data=log_data)
            
            # Create columns
            columns = []
            for col_name in log_data.keys():
                columns.append(TableColumn(field=col_name, title=col_name.capitalize()))
            
            # Create table
            table = DataTable(
                source=source,
                columns=columns,
                width=800,
                height=400,
                index_position=None
            )
            widgets.append(table)
        else:
            widgets.append(Div(text='<p>No log messages available</p>'))
        
        content = column(*widgets, sizing_mode='stretch_width')
        return content, 'Log'
    
    def _get_log_data(self):
        """Get log data.
        
        Returns:
            dict: Log data dictionary
        """
        # Get data from global log storage
        all_logs = []
        for key, logs in _log_storage.items():
            all_logs.extend(list(logs))
        
        if not all_logs:
            return None
        
        # Sort by time (newest first)
        all_logs = list(reversed(all_logs))
        
        # Convert to column data format
        return {
            'time': [log.get('time', '') for log in all_logs],
            'level': [log.get('level', '') for log in all_logs],
            'message': [log.get('message', '') for log in all_logs],
        }


def LogTabs(cols):
    """Create log tab class with custom columns.
    
    Args:
        cols: Column configuration
        
    Returns:
        Custom LogTab class
    """
    return type('LogTab', (LogTab,), {'cols': cols})
