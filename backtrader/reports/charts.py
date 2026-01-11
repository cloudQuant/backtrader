#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
报告专用图表生成器

生成报告所需的静态图表，区别于交互式绘图
"""

import io
import base64

try:
    import matplotlib
    matplotlib.use('Agg')  # 使用非交互式后端
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


class ReportChart:
    """报告专用图表生成器
    
    生成报告所需的静态图表，包括：
    - 权益曲线图（含买入持有对比线）
    - 收益率柱状图（自动周期判断）
    - 回撤面积图
    
    属性:
        figsize: 图表默认尺寸
        dpi: 图表分辨率
    """
    
    def __init__(self, figsize=(10, 3), dpi=100):
        """初始化图表生成器
        
        Args:
            figsize: 图表尺寸 (宽, 高)
            dpi: 图表分辨率
        """
        self.figsize = figsize
        self.dpi = dpi
        self._figures = []
    
    def plot_equity_curve(self, dates, values, benchmark_dates=None, 
                          benchmark_values=None, title='Equity Curve'):
        """绘制权益曲线图
        
        Args:
            dates: 日期列表
            values: 权益值列表
            benchmark_dates: 基准日期列表（可选）
            benchmark_values: 基准值列表（可选，如买入持有）
            title: 图表标题
            
        Returns:
            matplotlib.figure.Figure 或 None
        """
        if not MATPLOTLIB_AVAILABLE or not dates or not values:
            return None
        
        fig, ax = plt.subplots(1, 1, figsize=self.figsize, dpi=self.dpi)
        
        # 归一化到100
        start_value = values[0] if values[0] != 0 else 1
        normalized_values = [100 * v / start_value for v in values]
        
        # 绘制权益曲线
        ax.plot(dates, normalized_values, label='Strategy', linewidth=1.5, color='#3498DB')
        
        # 绘制买入持有对比线
        if benchmark_dates and benchmark_values:
            ax.plot(benchmark_dates, benchmark_values, label='Buy & Hold', 
                   linewidth=1, color='gray', linestyle='--')
        
        # 绘制基准线 (100)
        ax.axhline(y=100, color='gray', linestyle=':', linewidth=0.8, alpha=0.7)
        
        ax.set_ylabel('Net Asset Value (start=100)')
        ax.set_title(title)
        ax.legend(loc='upper left')
        ax.grid(True, alpha=0.3)
        
        # 格式化x轴日期
        if len(dates) > 0:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            plt.xticks(rotation=45)
        
        plt.tight_layout()
        self._figures.append(fig)
        
        return fig
    
    def plot_return_bars(self, dates, values, period='auto', title=None):
        """绘制收益率柱状图
        
        Args:
            dates: 日期列表
            values: 权益值列表
            period: 周期 ('auto', 'daily', 'weekly', 'monthly', 'yearly')
            title: 图表标题
            
        Returns:
            matplotlib.figure.Figure 或 None
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            return None
        
        if not dates or not values:
            return None
        
        # 创建 Series
        series = pd.Series(data=values, index=pd.to_datetime(dates))
        
        # 自动判断周期
        if period == 'auto':
            period_name, period_code = self._get_periodicity(dates)
        else:
            period_map = {
                'daily': ('Daily', 'D'),
                'weekly': ('Weekly', 'W'),
                'monthly': ('Monthly', 'ME'),
                'yearly': ('Yearly', 'YE'),
            }
            period_name, period_code = period_map.get(period, ('Daily', 'D'))
        
        # 重采样计算收益率
        try:
            resampled = series.resample(period_code).last()
            returns = 100 * resampled.pct_change().dropna()
        except Exception:
            return None
        
        if len(returns) == 0:
            return None
        
        fig, ax = plt.subplots(1, 1, figsize=self.figsize, dpi=self.dpi)
        
        # 根据正负值设置颜色
        colors = ['green' if r > 0 else 'red' for r in returns.values]
        
        # 绘制柱状图
        x_labels = [d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d) 
                   for d in returns.index]
        ax.bar(range(len(returns)), returns.values, color=colors, alpha=0.7)
        
        # 设置x轴标签
        if len(x_labels) <= 20:
            ax.set_xticks(range(len(returns)))
            ax.set_xticklabels(x_labels, rotation=45, ha='right')
        else:
            # 太多标签时只显示部分
            step = len(x_labels) // 10
            ax.set_xticks(range(0, len(returns), step))
            ax.set_xticklabels(x_labels[::step], rotation=45, ha='right')
        
        ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
        ax.set_ylabel('Return (%)')
        ax.set_title(title or f'{period_name} Returns')
        ax.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        self._figures.append(fig)
        
        return fig
    
    def plot_drawdown(self, dates, values, title='Drawdown'):
        """绘制回撤面积图
        
        Args:
            dates: 日期列表
            values: 权益值列表
            title: 图表标题
            
        Returns:
            matplotlib.figure.Figure 或 None
        """
        if not MATPLOTLIB_AVAILABLE or not dates or not values:
            return None
        
        # 计算回撤
        running_max = values[0]
        drawdowns = []
        
        for v in values:
            if v > running_max:
                running_max = v
            dd = (v - running_max) / running_max * 100 if running_max != 0 else 0
            drawdowns.append(dd)
        
        fig, ax = plt.subplots(1, 1, figsize=self.figsize, dpi=self.dpi)
        
        # 绘制回撤面积
        ax.fill_between(dates, drawdowns, 0, alpha=0.3, color='red', label='Drawdown')
        ax.plot(dates, drawdowns, color='red', linewidth=1)
        
        ax.set_ylabel('Drawdown (%)')
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        
        # 显示最大回撤
        max_dd = min(drawdowns)
        max_dd_idx = drawdowns.index(max_dd)
        ax.annotate(f'Max: {max_dd:.2f}%', 
                   xy=(dates[max_dd_idx], max_dd),
                   xytext=(10, 10), textcoords='offset points',
                   fontsize=9, color='red')
        
        # 格式化x轴日期
        if len(dates) > 0:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            plt.xticks(rotation=45)
        
        plt.tight_layout()
        self._figures.append(fig)
        
        return fig
    
    def _get_periodicity(self, dates):
        """智能判断最佳显示周期
        
        Args:
            dates: 日期列表
            
        Returns:
            tuple: (周期名称, 周期代码)
        """
        if not dates or len(dates) < 2:
            return ('Daily', 'D')
        
        try:
            start_date = dates[0]
            end_date = dates[-1]
            
            if hasattr(start_date, 'days'):
                time_interval_days = (end_date - start_date).days
            else:
                from datetime import datetime
                if isinstance(start_date, datetime):
                    time_interval_days = (end_date - start_date).days
                else:
                    time_interval_days = 30  # 默认
            
            if time_interval_days > 5 * 365.25:
                return ('Yearly', 'YE')
            elif time_interval_days > 365.25:
                return ('Monthly', 'ME')
            elif time_interval_days > 50:
                return ('Weekly', 'W')
            elif time_interval_days > 5:
                return ('Daily', 'D')
            elif time_interval_days > 0.5:
                return ('Hourly', 'H')
            else:
                return ('Per Minute', 'T')
        except Exception:
            return ('Daily', 'D')
    
    def save_to_file(self, fig, filename, format='png'):
        """保存图表到文件
        
        Args:
            fig: matplotlib figure 对象
            filename: 输出文件名
            format: 图片格式 ('png', 'jpg', 'svg', 'pdf')
        """
        if fig is None:
            return
        
        fig.savefig(filename, format=format, dpi=self.dpi, bbox_inches='tight')
    
    def to_base64(self, fig, format='png'):
        """将图表转换为 base64 编码
        
        Args:
            fig: matplotlib figure 对象
            format: 图片格式
            
        Returns:
            str: base64 编码的图片数据
        """
        if fig is None:
            return ''
        
        buf = io.BytesIO()
        fig.savefig(buf, format=format, dpi=self.dpi, bbox_inches='tight')
        buf.seek(0)
        
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        buf.close()
        
        return f'data:image/{format};base64,{img_base64}'
    
    def close_all(self):
        """关闭所有图表，释放内存"""
        for fig in self._figures:
            plt.close(fig)
        self._figures = []
