#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
分析器标签页

显示所有分析器的结果
"""

from ..tab import BokehTab

try:
    from bokeh.models import ColumnDataSource, DataTable, TableColumn
    from bokeh.models.widgets import Div
    from bokeh.layouts import column
    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False


class AnalyzerTab(BokehTab):
    """分析器标签页
    
    显示策略中所有分析器的分析结果。
    """
    
    def _is_useable(self):
        """判断是否可用
        
        当策略有分析器时可用
        """
        if not BOKEH_AVAILABLE:
            return False
        strategy = self.strategy
        if strategy is None:
            return False
        return len(getattr(strategy, 'analyzers', [])) > 0
    
    def _get_panel(self):
        """获取面板内容
        
        Returns:
            tuple: (widget, title)
        """
        strategy = self.strategy
        scheme = self.scheme
        
        # 创建分析器结果展示
        widgets = []
        
        for analyzer in strategy.analyzers:
            analyzer_name = analyzer.__class__.__name__
            
            # 获取分析结果
            try:
                analysis = analyzer.get_analysis()
            except Exception:
                analysis = {}
            
            # 创建标题
            title_div = Div(
                text=f'<h3 style="color: {scheme.text_color if scheme else "#333"};">{analyzer_name}</h3>',
                sizing_mode='stretch_width'
            )
            widgets.append(title_div)
            
            # 将分析结果转换为表格数据
            data = self._flatten_analysis(analysis)
            
            if data:
                source = ColumnDataSource(data={
                    'key': list(data.keys()),
                    'value': [str(v) for v in data.values()]
                })
                
                columns = [
                    TableColumn(field='key', title='Metric'),
                    TableColumn(field='value', title='Value'),
                ]
                
                table = DataTable(
                    source=source,
                    columns=columns,
                    width=400,
                    height=min(len(data) * 25 + 30, 300),
                    index_position=None
                )
                widgets.append(table)
            else:
                empty_div = Div(text='<p>No data available</p>')
                widgets.append(empty_div)
        
        content = column(*widgets, sizing_mode='stretch_width')
        return content, 'Analyzers'
    
    def _flatten_analysis(self, analysis, prefix=''):
        """将嵌套的分析结果扁平化
        
        Args:
            analysis: 分析结果字典
            prefix: 键前缀
            
        Returns:
            dict: 扁平化后的字典
        """
        result = {}
        
        if isinstance(analysis, dict):
            for key, value in analysis.items():
                new_key = f'{prefix}.{key}' if prefix else str(key)
                if isinstance(value, dict):
                    result.update(self._flatten_analysis(value, new_key))
                else:
                    result[new_key] = value
        else:
            result[prefix or 'value'] = analysis
        
        return result
