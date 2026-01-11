#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
辅助工具函数
"""

import re


def get_datanames(strategy):
    """获取策略中所有数据源的名称
    
    Args:
        strategy: 策略实例
        
    Returns:
        list: 数据源名称列表
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
    """获取策略标签
    
    Args:
        strategy: 策略实例
        
    Returns:
        str: 策略标签
    """
    if strategy is None:
        return 'Unknown Strategy'
    
    return strategy.__class__.__name__


def sanitize_source_name(name):
    """清理数据源名称，移除非法字符
    
    Args:
        name: 原始名称
        
    Returns:
        str: 清理后的名称
    """
    if name is None:
        return 'unnamed'
    
    # 移除非字母数字和下划线的字符
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', str(name))
    
    # 确保不以数字开头
    if sanitized and sanitized[0].isdigit():
        sanitized = '_' + sanitized
    
    return sanitized or 'unnamed'


def get_indicator_label(indicator):
    """获取指标标签
    
    Args:
        indicator: 指标实例
        
    Returns:
        str: 指标标签
    """
    if indicator is None:
        return 'Unknown Indicator'
    
    label = indicator.__class__.__name__
    
    # 添加参数信息（如果有）
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
            label += f' ({", ".join(params[:3])})'  # 最多显示3个参数
    
    return label


def format_datetime(dt, fmt='%Y-%m-%d %H:%M'):
    """格式化日期时间
    
    Args:
        dt: datetime 对象
        fmt: 格式字符串
        
    Returns:
        str: 格式化后的字符串
    """
    if dt is None:
        return ''
    
    try:
        return dt.strftime(fmt)
    except Exception:
        return str(dt)


def format_number(value, precision=2):
    """格式化数字
    
    Args:
        value: 数值
        precision: 小数精度
        
    Returns:
        str: 格式化后的字符串
    """
    if value is None:
        return 'N/A'
    
    try:
        return f'{float(value):.{precision}f}'
    except (ValueError, TypeError):
        return str(value)


def get_color_from_value(value, up_color='#26a69a', down_color='#ef5350', neutral_color='#666666'):
    """根据值获取颜色
    
    Args:
        value: 数值
        up_color: 正值颜色
        down_color: 负值颜色
        neutral_color: 零值颜色
        
    Returns:
        str: 颜色值
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
