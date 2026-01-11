#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
绩效指标标签页

显示策略的关键绩效指标
"""

from ..tab import BokehTab

try:
    from bokeh.models import ColumnDataSource, DataTable, TableColumn
    from bokeh.models.widgets import Div
    from bokeh.layouts import column, row
    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False


class PerformanceTab(BokehTab):
    """绩效指标标签页
    
    显示策略的关键绩效指标，包括：
    - 总收益率
    - 年化收益率
    - 夏普比率
    - 最大回撤
    - 胜率
    - 盈亏比
    - 交易统计
    """
    
    def _is_useable(self):
        """当有策略时可用"""
        if not BOKEH_AVAILABLE:
            return False
        return self.strategy is not None
    
    def _get_panel(self):
        """获取面板内容
        
        Returns:
            tuple: (widget, title)
        """
        strategy = self.strategy
        scheme = self.scheme
        
        # 获取主题颜色
        bg_color = scheme.body_background_color if scheme else '#ffffff'
        text_color = scheme.text_color if scheme else '#333333'
        title_color = scheme.text_color if scheme else '#333333'
        positive_color = '#4caf50'
        negative_color = '#f44336'
        
        widgets = []
        
        # 标题
        widgets.append(Div(
            text=f'<h2 style="color: {title_color}; margin-bottom: 20px;">Performance Metrics</h2>',
            sizing_mode='stretch_width'
        ))
        
        # 收集绩效数据
        metrics = self._collect_metrics(strategy)
        
        # 创建概要卡片
        summary_html = self._create_summary_cards(metrics, scheme)
        widgets.append(Div(text=summary_html, sizing_mode='stretch_width'))
        
        # 收益指标表格
        returns_data = self._get_returns_metrics(metrics)
        if returns_data:
            widgets.append(Div(
                text=f'<h3 style="color: {title_color}; margin-top: 20px;">Returns</h3>',
                sizing_mode='stretch_width'
            ))
            widgets.append(self._create_metrics_table(returns_data))
        
        # 风险指标表格
        risk_data = self._get_risk_metrics(metrics)
        if risk_data:
            widgets.append(Div(
                text=f'<h3 style="color: {title_color}; margin-top: 20px;">Risk</h3>',
                sizing_mode='stretch_width'
            ))
            widgets.append(self._create_metrics_table(risk_data))
        
        # 交易统计表格
        trade_data = self._get_trade_metrics(metrics)
        if trade_data:
            widgets.append(Div(
                text=f'<h3 style="color: {title_color}; margin-top: 20px;">Trade Statistics</h3>',
                sizing_mode='stretch_width'
            ))
            widgets.append(self._create_metrics_table(trade_data))
        
        content = column(*widgets, sizing_mode='stretch_width')
        return content, 'Performance'
    
    def _collect_metrics(self, strategy):
        """收集所有绩效指标
        
        Args:
            strategy: 策略实例
            
        Returns:
            dict: 绩效指标字典
        """
        metrics = {}
        
        # 从分析器获取指标
        for analyzer in getattr(strategy, 'analyzers', []):
            analyzer_name = analyzer.__class__.__name__
            try:
                analysis = analyzer.get_analysis()
                
                if analyzer_name == 'SharpeRatio':
                    metrics['sharpe_ratio'] = analysis.get('sharperatio', None)
                    
                elif analyzer_name == 'DrawDown':
                    dd = analysis.get('drawdown', {})
                    metrics['max_drawdown'] = analysis.get('max', {}).get('drawdown', None)
                    metrics['max_drawdown_len'] = analysis.get('max', {}).get('len', None)
                    
                elif analyzer_name == 'TradeAnalyzer':
                    total = analysis.get('total', {})
                    metrics['total_trades'] = total.get('total', 0)
                    metrics['total_open'] = total.get('open', 0)
                    metrics['total_closed'] = total.get('closed', 0)
                    
                    won = analysis.get('won', {})
                    lost = analysis.get('lost', {})
                    metrics['won_trades'] = won.get('total', 0)
                    metrics['lost_trades'] = lost.get('total', 0)
                    
                    if metrics['total_closed'] > 0:
                        metrics['win_rate'] = metrics['won_trades'] / metrics['total_closed'] * 100
                    
                    pnl = analysis.get('pnl', {})
                    metrics['gross_pnl'] = pnl.get('gross', {}).get('total', None)
                    metrics['net_pnl'] = pnl.get('net', {}).get('total', None)
                    
                    streak = analysis.get('streak', {})
                    metrics['max_win_streak'] = streak.get('won', {}).get('longest', 0)
                    metrics['max_lose_streak'] = streak.get('lost', {}).get('longest', 0)
                    
                elif analyzer_name == 'AnnualReturn':
                    if analysis:
                        # 计算平均年化收益
                        returns = list(analysis.values())
                        if returns:
                            metrics['annual_returns'] = analysis
                            metrics['avg_annual_return'] = sum(returns) / len(returns) * 100
                            
                elif analyzer_name == 'SQN':
                    metrics['sqn'] = analysis.get('sqn', None)
                    
                elif analyzer_name == 'TimeReturn':
                    if analysis:
                        returns = list(analysis.values())
                        if returns:
                            total_return = 1
                            for r in returns:
                                total_return *= (1 + r)
                            metrics['total_return'] = (total_return - 1) * 100
                            
            except Exception:
                pass
        
        # 从 broker 获取资金信息
        if hasattr(strategy, 'broker'):
            try:
                broker = strategy.broker
                start_cash = getattr(broker, 'startingcash', 100000)
                end_value = broker.getvalue()
                metrics['start_cash'] = start_cash
                metrics['end_value'] = end_value
                if 'total_return' not in metrics and start_cash > 0:
                    metrics['total_return'] = (end_value - start_cash) / start_cash * 100
            except Exception:
                pass
        
        return metrics
    
    def _create_summary_cards(self, metrics, scheme):
        """创建概要卡片 HTML
        
        Args:
            metrics: 指标字典
            scheme: 主题
            
        Returns:
            str: HTML 字符串
        """
        bg_color = scheme.body_background_color if scheme else '#f5f5f5'
        text_color = scheme.text_color if scheme else '#333'
        
        cards = []
        
        # 总收益率
        total_return = metrics.get('total_return')
        if total_return is not None:
            color = '#4caf50' if total_return >= 0 else '#f44336'
            cards.append(f'''
                <div style="background: {bg_color}; padding: 15px; border-radius: 8px; text-align: center; min-width: 150px;">
                    <div style="color: {text_color}; font-size: 12px; opacity: 0.8;">Total Return</div>
                    <div style="color: {color}; font-size: 24px; font-weight: bold;">{total_return:+.2f}%</div>
                </div>
            ''')
        
        # 夏普比率
        sharpe = metrics.get('sharpe_ratio')
        if sharpe is not None:
            color = '#4caf50' if sharpe >= 1 else ('#ff9800' if sharpe >= 0 else '#f44336')
            cards.append(f'''
                <div style="background: {bg_color}; padding: 15px; border-radius: 8px; text-align: center; min-width: 150px;">
                    <div style="color: {text_color}; font-size: 12px; opacity: 0.8;">Sharpe Ratio</div>
                    <div style="color: {color}; font-size: 24px; font-weight: bold;">{sharpe:.2f}</div>
                </div>
            ''')
        
        # 最大回撤
        max_dd = metrics.get('max_drawdown')
        if max_dd is not None:
            color = '#4caf50' if max_dd < 10 else ('#ff9800' if max_dd < 20 else '#f44336')
            cards.append(f'''
                <div style="background: {bg_color}; padding: 15px; border-radius: 8px; text-align: center; min-width: 150px;">
                    <div style="color: {text_color}; font-size: 12px; opacity: 0.8;">Max Drawdown</div>
                    <div style="color: {color}; font-size: 24px; font-weight: bold;">{max_dd:.2f}%</div>
                </div>
            ''')
        
        # 胜率
        win_rate = metrics.get('win_rate')
        if win_rate is not None:
            color = '#4caf50' if win_rate >= 50 else '#f44336'
            cards.append(f'''
                <div style="background: {bg_color}; padding: 15px; border-radius: 8px; text-align: center; min-width: 150px;">
                    <div style="color: {text_color}; font-size: 12px; opacity: 0.8;">Win Rate</div>
                    <div style="color: {color}; font-size: 24px; font-weight: bold;">{win_rate:.1f}%</div>
                </div>
            ''')
        
        # 总交易数
        total_trades = metrics.get('total_trades', 0)
        cards.append(f'''
            <div style="background: {bg_color}; padding: 15px; border-radius: 8px; text-align: center; min-width: 150px;">
                <div style="color: {text_color}; font-size: 12px; opacity: 0.8;">Total Trades</div>
                <div style="color: {text_color}; font-size: 24px; font-weight: bold;">{total_trades}</div>
            </div>
        ''')
        
        html = f'''
            <div style="display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 20px;">
                {''.join(cards)}
            </div>
        '''
        return html
    
    def _get_returns_metrics(self, metrics):
        """获取收益相关指标
        
        Returns:
            dict: 指标字典
        """
        data = {}
        
        if 'start_cash' in metrics:
            data['Starting Capital'] = f"${metrics['start_cash']:,.2f}"
        if 'end_value' in metrics:
            data['Ending Value'] = f"${metrics['end_value']:,.2f}"
        if 'total_return' in metrics:
            data['Total Return'] = f"{metrics['total_return']:+.2f}%"
        if 'avg_annual_return' in metrics:
            data['Avg Annual Return'] = f"{metrics['avg_annual_return']:+.2f}%"
        if 'net_pnl' in metrics and metrics['net_pnl'] is not None:
            data['Net P&L'] = f"${metrics['net_pnl']:,.2f}"
            
        return data
    
    def _get_risk_metrics(self, metrics):
        """获取风险相关指标
        
        Returns:
            dict: 指标字典
        """
        data = {}
        
        if 'sharpe_ratio' in metrics and metrics['sharpe_ratio'] is not None:
            data['Sharpe Ratio'] = f"{metrics['sharpe_ratio']:.3f}"
        if 'sqn' in metrics and metrics['sqn'] is not None:
            data['SQN'] = f"{metrics['sqn']:.2f}"
        if 'max_drawdown' in metrics and metrics['max_drawdown'] is not None:
            data['Max Drawdown'] = f"{metrics['max_drawdown']:.2f}%"
        if 'max_drawdown_len' in metrics and metrics['max_drawdown_len'] is not None:
            data['Max DD Duration'] = f"{metrics['max_drawdown_len']} bars"
            
        return data
    
    def _get_trade_metrics(self, metrics):
        """获取交易统计指标
        
        Returns:
            dict: 指标字典
        """
        data = {}
        
        if 'total_trades' in metrics:
            data['Total Trades'] = str(metrics['total_trades'])
        if 'total_closed' in metrics:
            data['Closed Trades'] = str(metrics['total_closed'])
        if 'total_open' in metrics:
            data['Open Trades'] = str(metrics['total_open'])
        if 'won_trades' in metrics:
            data['Winning Trades'] = str(metrics['won_trades'])
        if 'lost_trades' in metrics:
            data['Losing Trades'] = str(metrics['lost_trades'])
        if 'win_rate' in metrics:
            data['Win Rate'] = f"{metrics['win_rate']:.1f}%"
        if 'max_win_streak' in metrics:
            data['Max Win Streak'] = str(metrics['max_win_streak'])
        if 'max_lose_streak' in metrics:
            data['Max Lose Streak'] = str(metrics['max_lose_streak'])
            
        return data
    
    def _create_metrics_table(self, data):
        """创建指标表格
        
        Args:
            data: 指标字典
            
        Returns:
            DataTable
        """
        source = ColumnDataSource(data={
            'metric': list(data.keys()),
            'value': list(data.values())
        })
        
        columns = [
            TableColumn(field='metric', title='Metric', width=200),
            TableColumn(field='value', title='Value', width=150),
        ]
        
        table = DataTable(
            source=source,
            columns=columns,
            width=400,
            height=min(len(data) * 28 + 30, 300),
            index_position=None
        )
        
        return table
