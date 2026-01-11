#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Helper utility functions.
"""

import re


def get_datanames(strategy):
    """Get names of all data sources in strategy.
    
    Args:
        strategy: Strategy instance
        
    Returns:
        list: List of data source names
    """
    datanames = []
    
    if strategy is None or not hasattr(strategy, 'datas'):
        return datanames
    
    for i, data in enumerate(strategy.datas):
        if hasattr(data, '_name') and data._name:
            datanames.append(data._name)
        else:
            datanames.append(f'Data{i}')
    
    return datanames


def get_strategy_label(strategy):
    """Get strategy label.
    
    Args:
        strategy: Strategy instance
        
    Returns:
        str: Strategy label
    """
    if strategy is None:
        return 'Unknown Strategy'
    
    return strategy.__class__.__name__


def sanitize_source_name(name):
    """Sanitize data source name, remove illegal characters.
    
    Args:
        name: Original name
        
    Returns:
        str: Sanitized name
    """
    if name is None:
        return 'unnamed'
    
    # Remove non-alphanumeric and underscore characters
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', str(name))
    
    # Ensure it doesn't start with a digit
    if sanitized and sanitized[0].isdigit():
        sanitized = '_' + sanitized
    
    return sanitized or 'unnamed'


def get_indicator_label(indicator):
    """Get indicator label.
    
    Args:
        indicator: Indicator instance
        
    Returns:
        str: Indicator label
    """
    if indicator is None:
        return 'Unknown Indicator'
    
    label = indicator.__class__.__name__
    
    # Add parameter info (if available)
    if hasattr(indicator, 'params'):
        params = []
        for name in dir(indicator.params):
            if not name.startswith('_'):
                try:
                    value = getattr(indicator.params, name)
                    if not callable(value):
                        params.append(f'{name}={value}')
                except Exception:
                    pass
        if params:
            label += f' ({", ".join(params[:3])})'  # Show max 3 parameters
    
    return label


def format_datetime(dt, fmt='%Y-%m-%d %H:%M'):
    """Format datetime.
    
    Args:
        dt: datetime object
        fmt: Format string
        
    Returns:
        str: Formatted string
    """
    if dt is None:
        return ''
    
    try:
        return dt.strftime(fmt)
    except Exception:
        return str(dt)


def format_number(value, precision=2):
    """Format number.
    
    Args:
        value: Numeric value
        precision: Decimal precision
        
    Returns:
        str: Formatted string
    """
    if value is None:
        return 'N/A'
    
    try:
        return f'{float(value):.{precision}f}'
    except (ValueError, TypeError):
        return str(value)


def get_color_from_value(value, up_color='#26a69a', down_color='#ef5350', neutral_color='#666666'):
    """Get color based on value.
    
    Args:
        value: Numeric value
        up_color: Color for positive values
        down_color: Color for negative values
        neutral_color: Color for zero values
        
    Returns:
        str: Color value
    """
    if value is None:
        return neutral_color
    
    try:
        val = float(value)
        if val > 0:
            return up_color
        elif val < 0:
            return down_color
        else:
            return neutral_color
    except (ValueError, TypeError):
        return neutral_color
