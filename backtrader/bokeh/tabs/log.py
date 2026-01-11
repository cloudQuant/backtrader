#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
日志标签页

显示策略运行日志
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

# 全局日志存储
_log_storage = {}


class LogHandler(logging.Handler):
    """日志处理器
    
    捕获日志消息并存储到指定的存储中
    """
    
    def __init__(self, storage_key, max_records=1000):
        super().__init__()
        self.storage_key = storage_key
        self.max_records = max_records
        if storage_key not in _log_storage:
            _log_storage[storage_key] = deque(maxlen=max_records)
    
    def emit(self, record):
        log_entry = {
            'time': self.format(record).split(' - ')[0] if ' - ' in self.format(record) else '',
            'level': record.levelname,
            'message': record.getMessage()
        }
        _log_storage[self.storage_key].append(log_entry)


def getlogger(name='backtrader', col=None):
    """获取带有日志处理器的 logger
    
    Args:
        name: logger 名称
        col: 自定义列（可选）
        
    Returns:
        logging.Logger 实例
    """
    logger = logging.getLogger(name)
    
    # 检查是否已添加 LogHandler
    has_handler = any(isinstance(h, LogHandler) for h in logger.handlers)
    if not has_handler:
        handler = LogHandler(name)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
    
    return logger


class LogTab(BokehTab):
    """日志标签页
    
    显示策略运行过程中的日志信息。
    
    属性:
        cols: 显示的列配置
    """
    
    cols = ['Time', 'Level', 'Message']  # 默认列
    
    def __init__(self, app, figurepage, client=None, cols=None):
        super().__init__(app, figurepage, client)
        if cols is not None:
            self.cols = cols
    
    def _is_useable(self):
        """日志标签页始终可用"""
        return BOKEH_AVAILABLE
    
    def _get_panel(self):
        """获取面板内容
        
        Returns:
            tuple: (widget, title)
        """
        scheme = self.scheme
        text_color = scheme.text_color if scheme else '#333'
        
        widgets = []
        
        # 标题
        widgets.append(Div(
            text=f'<h3 style="color: {text_color};">Log Messages</h3>',
            sizing_mode='stretch_width'
        ))
        
        # 获取日志数据
        log_data = self._get_log_data()
        
        if log_data:
            # 创建数据源
            source = ColumnDataSource(data=log_data)
            
            # 创建列
            columns = []
            for col_name in log_data.keys():
                columns.append(TableColumn(field=col_name, title=col_name.capitalize()))
            
            # 创建表格
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
        """获取日志数据
        
        Returns:
            dict: 日志数据字典
        """
        # 从全局日志存储获取数据
        all_logs = []
        for key, logs in _log_storage.items():
            all_logs.extend(list(logs))
        
        if not all_logs:
            return None
        
        # 按时间排序（最新的在前）
        all_logs = list(reversed(all_logs))
        
        # 转换为列数据格式
        return {
            'time': [log.get('time', '') for log in all_logs],
            'level': [log.get('level', '') for log in all_logs],
            'message': [log.get('message', '') for log in all_logs],
        }


def LogTabs(cols):
    """创建自定义列的日志标签页类
    
    Args:
        cols: 列配置
        
    Returns:
        自定义的 LogTab 类
    """
    return type('LogTab', (LogTab,), {'cols': cols})
