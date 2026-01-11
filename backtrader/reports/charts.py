#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Report-specific chart generator.

Generates static charts for reports, distinct from interactive plotting.
"""

import io
import base64

try:
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
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
    """Report-specific chart generator.
    
    Generates static charts for reports, including:
    - Equity curve chart (with buy-and-hold comparison line)
    - Return bars chart (automatic period detection)
    - Drawdown area chart
    
    Attributes:
        figsize: Default chart size
        dpi: Chart resolution
    """
    
    def __init__(self, figsize=(10, 3), dpi=100):
        """Initialize the chart generator.
        
        Args:
            figsize: Chart size (width, height)
            dpi: Chart resolution
        """
        self.figsize = figsize
        self.dpi = dpi
        self._figures = []
    
    def plot_equity_curve(self, dates, values, benchmark_dates=None, 
                          benchmark_values=None, title='Equity Curve'):
        """Plot equity curve chart.
        
        Args:
            dates: List of dates
            values: List of equity values
            benchmark_dates: List of benchmark dates (optional)
            benchmark_values: List of benchmark values (optional, e.g., buy-and-hold)
            title: Chart title
            
        Returns:
            matplotlib.figure.Figure or None
        """
        if not MATPLOTLIB_AVAILABLE or not dates or not values:
            return None
        
        fig, ax = plt.subplots(1, 1, figsize=self.figsize, dpi=self.dpi)
        
        # Normalize to 100
        start_value = values[0] if values[0] != 0 else 1
        normalized_values = [100 * v / start_value for v in values]
        
        # Plot equity curve
        ax.plot(dates, normalized_values, label='Strategy', linewidth=1.5, color='#3498DB')
        
        # Plot buy-and-hold comparison line
        if benchmark_dates and benchmark_values:
            ax.plot(benchmark_dates, benchmark_values, label='Buy & Hold', 
                   linewidth=1, color='gray', linestyle='--')
        
        # Plot baseline (100)
        ax.axhline(y=100, color='gray', linestyle=':', linewidth=0.8, alpha=0.7)
        
        ax.set_ylabel('Net Asset Value (start=100)')
        ax.set_title(title)
        ax.legend(loc='upper left')
        ax.grid(True, alpha=0.3)
        
        # Format x-axis dates
        if len(dates) > 0:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            plt.xticks(rotation=45)
        
        plt.tight_layout()
        self._figures.append(fig)
        
        return fig
    
    def plot_return_bars(self, dates, values, period='auto', title=None):
        """Plot return bars chart.
        
        Args:
            dates: List of dates
            values: List of equity values
            period: Period ('auto', 'daily', 'weekly', 'monthly', 'yearly')
            title: Chart title
            
        Returns:
            matplotlib.figure.Figure or None
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            return None
        
        if not dates or not values:
            return None
        
        # Create Series
        series = pd.Series(data=values, index=pd.to_datetime(dates))
        
        # Auto-detect period
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
        
        # Resample and calculate returns
        try:
            resampled = series.resample(period_code).last()
            returns = 100 * resampled.pct_change().dropna()
        except Exception:
            return None
        
        if len(returns) == 0:
            return None
        
        fig, ax = plt.subplots(1, 1, figsize=self.figsize, dpi=self.dpi)
        
        # Set colors based on positive/negative values
        colors = ['green' if r > 0 else 'red' for r in returns.values]
        
        # Plot bar chart
        x_labels = [d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d) 
                   for d in returns.index]
        ax.bar(range(len(returns)), returns.values, color=colors, alpha=0.7)
        
        # Set x-axis labels
        if len(x_labels) <= 20:
            ax.set_xticks(range(len(returns)))
            ax.set_xticklabels(x_labels, rotation=45, ha='right')
        else:
            # Show only partial labels when too many
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
        """Plot drawdown area chart.
        
        Args:
            dates: List of dates
            values: List of equity values
            title: Chart title
            
        Returns:
            matplotlib.figure.Figure or None
        """
        if not MATPLOTLIB_AVAILABLE or not dates or not values:
            return None
        
        # Calculate drawdown
        running_max = values[0]
        drawdowns = []
        
        for v in values:
            if v > running_max:
                running_max = v
            dd = (v - running_max) / running_max * 100 if running_max != 0 else 0
            drawdowns.append(dd)
        
        fig, ax = plt.subplots(1, 1, figsize=self.figsize, dpi=self.dpi)
        
        # Plot drawdown area
        ax.fill_between(dates, drawdowns, 0, alpha=0.3, color='red', label='Drawdown')
        ax.plot(dates, drawdowns, color='red', linewidth=1)
        
        ax.set_ylabel('Drawdown (%)')
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        
        # Show maximum drawdown
        max_dd = min(drawdowns)
        max_dd_idx = drawdowns.index(max_dd)
        ax.annotate(f'Max: {max_dd:.2f}%', 
                   xy=(dates[max_dd_idx], max_dd),
                   xytext=(10, 10), textcoords='offset points',
                   fontsize=9, color='red')
        
        # Format x-axis dates
        if len(dates) > 0:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            plt.xticks(rotation=45)
        
        plt.tight_layout()
        self._figures.append(fig)
        
        return fig
    
    def _get_periodicity(self, dates):
        """Intelligently determine the best display period.
        
        Args:
            dates: List of dates
            
        Returns:
            tuple: (period name, period code)
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
                    time_interval_days = 30  # Default
            
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
        """Save chart to file.
        
        Args:
            fig: matplotlib figure object
            filename: Output filename
            format: Image format ('png', 'jpg', 'svg', 'pdf')
        """
        if fig is None:
            return
        
        fig.savefig(filename, format=format, dpi=self.dpi, bbox_inches='tight')
    
    def to_base64(self, fig, format='png'):
        """Convert chart to base64 encoding.
        
        Args:
            fig: matplotlib figure object
            format: Image format
            
        Returns:
            str: base64 encoded image data
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
        """Close all charts and release memory."""
        for fig in self._figures:
            plt.close(fig)
        self._figures = []
