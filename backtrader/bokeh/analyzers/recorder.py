#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
数据记录分析器

记录策略运行过程中的数据，用于后续绘图或分析
"""

import backtrader as bt
from collections import OrderedDict


class RecorderAnalyzer(bt.Analyzer):
    """数据记录分析器
    
    记录策略运行过程中的 OHLCV 数据和指标数据。
    
    参数:
        indicators: 是否记录指标数据
        observers: 是否记录观察器数据
    
    使用示例:
        cerebro.addanalyzer(RecorderAnalyzer, indicators=True)
        
        # 运行后获取数据
        result = cerebro.run()
        recorder = result[0].analyzers.recorderanalyzer
        data = recorder.get_analysis()
    """
    
    params = (
        ('indicators', True),   # 是否记录指标
        ('observers', False),   # 是否记录观察器
    )
    
    def __init__(self):
        super().__init__()
        
        # 数据存储
        self._data = OrderedDict()
        
        # 初始化数据源存储
        for i, data in enumerate(self.strategy.datas):
            name = getattr(data, '_name', None) or f'data{i}'
            self._data[name] = {
                'datetime': [],
                'open': [],
                'high': [],
                'low': [],
                'close': [],
                'volume': [],
            }
        
        # 初始化指标存储
        if self.p.indicators:
            self._indicators = OrderedDict()
        
        # 初始化观察器存储
        if self.p.observers:
            self._observers = OrderedDict()
    
    def start(self):
        """分析器启动"""
        pass
    
    def next(self):
        """记录每个 bar 的数据"""
        # 记录数据源
        for i, data in enumerate(self.strategy.datas):
            name = getattr(data, '_name', f'data{i}')
            
            if name in self._data:
                try:
                    self._data[name]['datetime'].append(data.datetime.datetime(0))
                    self._data[name]['open'].append(data.open[0])
                    self._data[name]['high'].append(data.high[0])
                    self._data[name]['low'].append(data.low[0])
                    self._data[name]['close'].append(data.close[0])
                    self._data[name]['volume'].append(data.volume[0] if hasattr(data, 'volume') else 0)
                except Exception:
                    pass
        
        # 记录指标
        if self.p.indicators and hasattr(self.strategy, '_lineiterators'):
            indicators = self.strategy._lineiterators.get(1, [])  # IndType = 1
            
            for ind in indicators:
                ind_name = ind.__class__.__name__
                
                if ind_name not in self._indicators:
                    self._indicators[ind_name] = OrderedDict()
                    # 初始化线存储
                    for line_name in ind.lines._getlinealiases():
                        self._indicators[ind_name][line_name] = []
                
                # 记录每条线的值
                for line_name in ind.lines._getlinealiases():
                    try:
                        line = getattr(ind.lines, line_name)
                        value = line[0] if len(line) > 0 else None
                        self._indicators[ind_name][line_name].append(value)
                    except Exception:
                        self._indicators[ind_name][line_name].append(None)
        
        # 记录观察器
        if self.p.observers and hasattr(self.strategy, '_lineiterators'):
            observers = self.strategy._lineiterators.get(2, [])  # ObsType = 2
            
            for obs in observers:
                obs_name = obs.__class__.__name__
                
                if obs_name not in self._observers:
                    self._observers[obs_name] = OrderedDict()
                    for line_name in obs.lines._getlinealiases():
                        self._observers[obs_name][line_name] = []
                
                for line_name in obs.lines._getlinealiases():
                    try:
                        line = getattr(obs.lines, line_name)
                        value = line[0] if len(line) > 0 else None
                        self._observers[obs_name][line_name].append(value)
                    except Exception:
                        self._observers[obs_name][line_name].append(None)
    
    def stop(self):
        """分析器停止"""
        pass
    
    def get_analysis(self):
        """返回记录的数据
        
        Returns:
            OrderedDict: 包含数据、指标和观察器的字典
        """
        result = OrderedDict()
        
        result['data'] = self._data
        
        if self.p.indicators:
            result['indicators'] = getattr(self, '_indicators', OrderedDict())
        
        if self.p.observers:
            result['observers'] = getattr(self, '_observers', OrderedDict())
        
        return result
    
    def get_dataframe(self, data_name=None):
        """将数据转换为 pandas DataFrame
        
        Args:
            data_name: 数据源名称，None 表示第一个数据源
            
        Returns:
            pandas.DataFrame 或 None
        """
        try:
            import pandas as pd
        except ImportError:
            return None
        
        if data_name is None:
            data_name = list(self._data.keys())[0] if self._data else None
        
        if data_name is None or data_name not in self._data:
            return None
        
        df = pd.DataFrame(self._data[data_name])
        
        if 'datetime' in df.columns:
            df.set_index('datetime', inplace=True)
        
        return df
