#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
性能指标计算器

从策略和分析器中提取并计算所有性能指标
"""

import math
from datetime import datetime


class PerformanceCalculator:
    """统一的性能指标计算器
    
    从策略和分析器中提取并计算所有性能指标，包括：
    - PnL指标：总收益、年化收益、累计收益率
    - 风险指标：最大回撤、夏普比率、SQN、卡玛比率
    - 交易统计：胜率、盈亏比、平均盈利/亏损
    
    属性:
        strategy: 策略实例
        
    使用示例:
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_all_metrics()
        print(f"夏普比率: {metrics['sharpe_ratio']}")
        print(f"SQN评级: {metrics['sqn_human']}")
    """
    
    def __init__(self, strategy):
        """初始化性能计算器
        
        Args:
            strategy: backtrader 策略实例（run()返回的结果）
        """
        self.strategy = strategy
        self._analyzers = getattr(strategy, 'analyzers', None)
        self._broker = getattr(strategy, 'broker', None)
    
    def get_all_metrics(self):
        """返回所有性能指标的字典
        
        Returns:
            dict: 包含所有性能指标的字典
        """
        metrics = {}
        metrics.update(self.get_pnl_metrics())
        metrics.update(self.get_risk_metrics())
        metrics.update(self.get_trade_metrics())
        metrics.update(self.get_kpi_metrics())
        return metrics
    
    def get_pnl_metrics(self):
        """获取收益相关指标
        
        Returns:
            dict: 收益指标字典
        """
        metrics = {
            'start_cash': self._get_start_cash(),
            'end_value': self._get_end_value(),
            'rpl': None,  # 已实现盈亏
            'total_return': None,  # 总收益率 %
            'annual_return': None,  # 年化收益率 %
            'result_won_trades': None,
            'result_lost_trades': None,
            'profit_factor': None,
            'rpl_per_trade': None,
        }
        
        # 计算基本收益
        start_cash = metrics['start_cash']
        end_value = metrics['end_value']
        
        if start_cash and end_value:
            metrics['rpl'] = end_value - start_cash
            metrics['total_return'] = 100 * (end_value / start_cash - 1)
        
        # 从 TradeAnalyzer 获取交易统计
        trade_analysis = self._get_analyzer_result('tradeanalyzer')
        if trade_analysis:
            pnl = trade_analysis.get('pnl', {})
            net = pnl.get('net', {})
            
            if 'total' in net:
                metrics['rpl'] = net['total']
            
            won = trade_analysis.get('won', {})
            lost = trade_analysis.get('lost', {})
            
            won_pnl = won.get('pnl', {})
            lost_pnl = lost.get('pnl', {})
            
            metrics['result_won_trades'] = won_pnl.get('total')
            metrics['result_lost_trades'] = lost_pnl.get('total')
            
            # 计算盈利因子
            if metrics['result_won_trades'] and metrics['result_lost_trades']:
                if metrics['result_lost_trades'] != 0:
                    metrics['profit_factor'] = abs(
                        metrics['result_won_trades'] / metrics['result_lost_trades']
                    )
            
            # 每笔交易平均盈亏
            total = trade_analysis.get('total', {})
            closed = total.get('closed', 0)
            if closed > 0 and metrics['rpl']:
                metrics['rpl_per_trade'] = metrics['rpl'] / closed
        
        # 计算年化收益
        bt_period_days = self._get_backtest_days()
        if bt_period_days and bt_period_days > 0 and metrics['total_return'] is not None:
            total_return_decimal = metrics['total_return'] / 100
            metrics['annual_return'] = 100 * (
                (1 + total_return_decimal) ** (365.25 / bt_period_days) - 1
            )
        
        return metrics
    
    def get_risk_metrics(self):
        """获取风险相关指标
        
        Returns:
            dict: 风险指标字典
        """
        metrics = {
            'max_money_drawdown': None,
            'max_pct_drawdown': None,
            'calmar_ratio': None,
        }
        
        # 从 DrawDown 分析器获取
        drawdown = self._get_analyzer_result('drawdown')
        if drawdown:
            max_dd = drawdown.get('max', {})
            metrics['max_money_drawdown'] = max_dd.get('moneydown')
            metrics['max_pct_drawdown'] = max_dd.get('drawdown')
        
        # 计算卡玛比率
        pnl_metrics = self.get_pnl_metrics()
        if pnl_metrics.get('annual_return') and metrics.get('max_pct_drawdown'):
            if metrics['max_pct_drawdown'] != 0:
                metrics['calmar_ratio'] = abs(
                    pnl_metrics['annual_return'] / metrics['max_pct_drawdown']
                )
        
        return metrics
    
    def get_trade_metrics(self):
        """获取交易统计指标
        
        Returns:
            dict: 交易统计字典
        """
        metrics = {
            'total_number_trades': 0,
            'trades_closed': 0,
            'trades_won': 0,
            'trades_lost': 0,
            'pct_winning': None,
            'pct_losing': None,
            'avg_money_winning': None,
            'avg_money_losing': None,
            'best_winning_trade': None,
            'worst_losing_trade': None,
            'avg_trade_duration': None,
        }
        
        trade_analysis = self._get_analyzer_result('tradeanalyzer')
        if trade_analysis:
            total = trade_analysis.get('total', {})
            metrics['total_number_trades'] = total.get('total', 0)
            metrics['trades_closed'] = total.get('closed', 0)
            
            won = trade_analysis.get('won', {})
            lost = trade_analysis.get('lost', {})
            
            metrics['trades_won'] = won.get('total', 0)
            metrics['trades_lost'] = lost.get('total', 0)
            
            # 胜率
            if metrics['trades_closed'] > 0:
                metrics['pct_winning'] = 100 * metrics['trades_won'] / metrics['trades_closed']
                metrics['pct_losing'] = 100 * metrics['trades_lost'] / metrics['trades_closed']
            
            # 平均盈亏
            won_pnl = won.get('pnl', {})
            lost_pnl = lost.get('pnl', {})
            
            metrics['avg_money_winning'] = won_pnl.get('average')
            metrics['avg_money_losing'] = lost_pnl.get('average')
            metrics['best_winning_trade'] = won_pnl.get('max')
            metrics['worst_losing_trade'] = lost_pnl.get('max')
            
            # 平均持仓时间
            len_info = trade_analysis.get('len', {})
            if isinstance(len_info, dict):
                total_len = len_info.get('total', {})
                if isinstance(total_len, dict):
                    metrics['avg_trade_duration'] = total_len.get('average')
        
        return metrics
    
    def get_kpi_metrics(self):
        """获取关键性能指标
        
        Returns:
            dict: KPI指标字典
        """
        metrics = {
            'sharpe_ratio': None,
            'sqn_score': None,
            'sqn_human': None,
            'sortino_ratio': None,
        }
        
        # 夏普比率
        sharpe = self._get_analyzer_result('sharperatio')
        if sharpe:
            metrics['sharpe_ratio'] = sharpe.get('sharperatio')
        
        # SQN
        sqn = self._get_analyzer_result('sqn')
        if sqn:
            sqn_score = sqn.get('sqn')
            metrics['sqn_score'] = sqn_score
            if sqn_score is not None:
                metrics['sqn_human'] = self.sqn_to_rating(sqn_score)
        
        # Sortino 比率
        sortino = self._get_analyzer_result('sortinoratio')
        if sortino:
            metrics['sortino_ratio'] = sortino.get('sortinoratio')
        
        return metrics
    
    def get_equity_curve(self):
        """获取权益曲线数据
        
        Returns:
            tuple: (dates, values) 日期和权益值列表
        """
        try:
            import pandas as pd
        except ImportError:
            return None, None
        
        dates = []
        values = []
        
        # 尝试从 Broker observer 获取
        if hasattr(self.strategy, 'observers'):
            for obs in self.strategy.observers:
                if obs.__class__.__name__ == 'Broker':
                    if hasattr(obs.lines, 'value'):
                        value_line = obs.lines.value
                        length = len(value_line)
                        
                        # 获取日期
                        if hasattr(self.strategy, 'data'):
                            data = self.strategy.data
                            from ..utils.date import num2date
                            # 正确的索引: 从 1-length 到 0
                            for i in range(length):
                                idx = 1 - length + i
                                try:
                                    dt_num = data.datetime[idx]
                                    dates.append(num2date(dt_num))
                                    values.append(value_line[idx])
                                except Exception:
                                    pass
                        break
        
        if not values:
            # 尝试从 TimeReturn 分析器获取并计算累计权益
            time_return = self._get_analyzer_result('timereturn')
            if time_return:
                start_cash = self._get_start_cash() or 100000
                cumulative_value = start_cash
                for dt, ret in sorted(time_return.items()):
                    cumulative_value = cumulative_value * (1 + ret)
                    dates.append(dt)
                    values.append(cumulative_value)
        
        if not values:
            # 如果仍然没有数据，从数据源计算买入持有的权益曲线作为替代
            benchmark_dates, benchmark_values = self.get_buynhold_curve()
            if benchmark_dates and benchmark_values:
                start_cash = self._get_start_cash() or 100000
                dates = benchmark_dates
                # 将归一化值转换为实际权益值
                values = [start_cash * v / 100 for v in benchmark_values]
        
        return dates, values
    
    def get_buynhold_curve(self):
        """获取买入持有对比曲线
        
        Returns:
            tuple: (dates, values) 日期和买入持有值列表
        """
        if not hasattr(self.strategy, 'data'):
            return None, None
        
        data = self.strategy.data
        dates = []
        values = []
        
        try:
            length = len(data)
            if length == 0:
                return None, None
            
            # 获取开盘价作为买入持有基准
            first_price = None
            
            from ..utils.date import num2date
            
            # 正确的索引: 从 1-length 到 0
            for i in range(length):
                idx = 1 - length + i
                try:
                    dt_num = data.datetime[idx]
                    dates.append(num2date(dt_num))
                    
                    price = data.open[idx]
                    if first_price is None:
                        first_price = price
                    
                    # 归一化到100
                    values.append(100 * price / first_price if first_price else 100)
                except Exception:
                    pass
        except Exception:
            pass
        
        return dates, values
    
    @staticmethod
    def sqn_to_rating(sqn_score):
        """SQN分数转人类评级
        
        参考: http://www.vantharp.com/tharp-concepts/sqn.asp
        
        Args:
            sqn_score: SQN分数
            
        Returns:
            str: 人类可读的评级
        """
        if sqn_score is None or math.isnan(sqn_score):
            return "N/A"
        
        if sqn_score < 1.6:
            return "Poor"
        elif sqn_score < 1.9:
            return "Below Average"
        elif sqn_score < 2.4:
            return "Average"
        elif sqn_score < 2.9:
            return "Good"
        elif sqn_score < 5.0:
            return "Excellent"
        elif sqn_score < 6.9:
            return "Superb"
        else:
            return "Holy Grail"
    
    def _get_start_cash(self):
        """获取初始资金"""
        if self._broker:
            return getattr(self._broker, 'startingcash', None)
        return None
    
    def _get_end_value(self):
        """获取最终价值"""
        if self._broker:
            return self._broker.getvalue()
        return None
    
    def _get_backtest_days(self):
        """获取回测天数"""
        if not hasattr(self.strategy, 'data'):
            return None
        
        data = self.strategy.data
        try:
            from ..utils.date import num2date
            
            length = len(data)
            if length < 2:
                return None
            
            # 正确的索引: 0是当前(最后)bar, 1-length是第一个bar
            start_dt = num2date(data.datetime[1 - length])
            end_dt = num2date(data.datetime[0])
            
            delta = end_dt - start_dt
            return delta.days
        except Exception:
            return None
    
    def _get_analyzer_result(self, name):
        """获取分析器结果
        
        Args:
            name: 分析器名称（不区分大小写）
            
        Returns:
            dict: 分析器结果，如果不存在则返回 None
        """
        if self._analyzers is None:
            return None
        
        # 尝试直接通过名称获取
        name_lower = name.lower()
        
        # 遍历所有分析器
        for analyzer in self._analyzers:
            analyzer_name = analyzer.__class__.__name__.lower()
            
            # 检查名称匹配
            if analyzer_name == name_lower or name_lower in analyzer_name:
                try:
                    return analyzer.get_analysis()
                except Exception:
                    pass
            
            # 检查 _name 属性
            custom_name = getattr(analyzer, '_name', '').lower()
            if name_lower in custom_name:
                try:
                    return analyzer.get_analysis()
                except Exception:
                    pass
        
        return None
    
    def get_strategy_info(self):
        """获取策略信息
        
        Returns:
            dict: 策略信息字典
        """
        info = {
            'strategy_name': self.strategy.__class__.__name__,
            'params': {},
        }
        
        # 获取策略参数
        if hasattr(self.strategy, 'params'):
            params = self.strategy.params
            for name in dir(params):
                if not name.startswith('_'):
                    try:
                        value = getattr(params, name)
                        if not callable(value):
                            info['params'][name] = value
                    except Exception:
                        pass
        
        return info
    
    def get_data_info(self):
        """获取数据信息
        
        Returns:
            dict: 数据信息字典
        """
        info = {
            'data_name': None,
            'start_date': None,
            'end_date': None,
            'bars': 0,
        }
        
        if not hasattr(self.strategy, 'data'):
            return info
        
        data = self.strategy.data
        
        # 数据名称
        info['data_name'] = getattr(data, '_name', None) or 'Data'
        
        try:
            from ..utils.date import num2date
            
            length = len(data)
            info['bars'] = length
            
            if length > 0:
                # 正确的索引: 0是当前(最后)bar, 1-length是第一个bar
                info['start_date'] = num2date(data.datetime[1 - length])
                info['end_date'] = num2date(data.datetime[0])
        except Exception:
            pass
        
        return info
