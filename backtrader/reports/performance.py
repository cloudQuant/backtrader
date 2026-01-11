#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Performance metrics calculator.

Extracts and calculates all performance metrics from strategies and analyzers.
"""

import math
from datetime import datetime


class PerformanceCalculator:
    """Unified performance metrics calculator.
    
    Extracts and calculates all performance metrics from strategies and analyzers, including:
    - PnL metrics: total return, annual return, cumulative return
    - Risk metrics: max drawdown, Sharpe ratio, SQN, Calmar ratio
    - Trade statistics: win rate, profit/loss ratio, average profit/loss
    
    Attributes:
        strategy: Strategy instance
        
    Usage example:
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_all_metrics()
        print(f"Sharpe ratio: {metrics['sharpe_ratio']}")
        print(f"SQN rating: {metrics['sqn_human']}")
    """
    
    def __init__(self, strategy):
        """Initialize the performance calculator.
        
        Args:
            strategy: backtrader strategy instance (result from run())
        """
        self.strategy = strategy
        self._analyzers = getattr(strategy, 'analyzers', None)
        self._broker = getattr(strategy, 'broker', None)
    
    def get_all_metrics(self):
        """Return dictionary of all performance metrics.
        
        Returns:
            dict: Dictionary containing all performance metrics
        """
        metrics = {}
        metrics.update(self.get_pnl_metrics())
        metrics.update(self.get_risk_metrics())
        metrics.update(self.get_trade_metrics())
        metrics.update(self.get_kpi_metrics())
        return metrics
    
    def get_pnl_metrics(self):
        """Get profit and loss related metrics.
        
        Returns:
            dict: PnL metrics dictionary
        """
        metrics = {
            'start_cash': self._get_start_cash(),
            'end_value': self._get_end_value(),
            'rpl': None,  # Realized profit/loss
            'total_return': None,  # Total return %
            'annual_return': None,  # Annual return %
            'result_won_trades': None,
            'result_lost_trades': None,
            'profit_factor': None,
            'rpl_per_trade': None,
        }
        
        # Calculate basic returns
        start_cash = metrics['start_cash']
        end_value = metrics['end_value']
        
        if start_cash and end_value:
            metrics['rpl'] = end_value - start_cash
            metrics['total_return'] = 100 * (end_value / start_cash - 1)
        
        # Get trade statistics from TradeAnalyzer
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
            
            # Calculate profit factor
            if metrics['result_won_trades'] and metrics['result_lost_trades']:
                if metrics['result_lost_trades'] != 0:
                    metrics['profit_factor'] = abs(
                        metrics['result_won_trades'] / metrics['result_lost_trades']
                    )
            
            # Average profit/loss per trade
            total = trade_analysis.get('total', {})
            closed = total.get('closed', 0)
            if closed > 0 and metrics['rpl']:
                metrics['rpl_per_trade'] = metrics['rpl'] / closed
        
        # Calculate annual return
        bt_period_days = self._get_backtest_days()
        if bt_period_days and bt_period_days > 0 and metrics['total_return'] is not None:
            total_return_decimal = metrics['total_return'] / 100
            metrics['annual_return'] = 100 * (
                (1 + total_return_decimal) ** (365.25 / bt_period_days) - 1
            )
        
        return metrics
    
    def get_risk_metrics(self):
        """Get risk-related metrics.
        
        Returns:
            dict: Risk metrics dictionary
        """
        metrics = {
            'max_money_drawdown': None,
            'max_pct_drawdown': None,
            'calmar_ratio': None,
        }
        
        # Get from DrawDown analyzer
        drawdown = self._get_analyzer_result('drawdown')
        if drawdown:
            max_dd = drawdown.get('max', {})
            metrics['max_money_drawdown'] = max_dd.get('moneydown')
            metrics['max_pct_drawdown'] = max_dd.get('drawdown')
        
        # Calculate Calmar ratio
        pnl_metrics = self.get_pnl_metrics()
        if pnl_metrics.get('annual_return') and metrics.get('max_pct_drawdown'):
            if metrics['max_pct_drawdown'] != 0:
                metrics['calmar_ratio'] = abs(
                    pnl_metrics['annual_return'] / metrics['max_pct_drawdown']
                )
        
        return metrics
    
    def get_trade_metrics(self):
        """Get trade statistics metrics.
        
        Returns:
            dict: Trade statistics dictionary
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
            
            # Win rate
            if metrics['trades_closed'] > 0:
                metrics['pct_winning'] = 100 * metrics['trades_won'] / metrics['trades_closed']
                metrics['pct_losing'] = 100 * metrics['trades_lost'] / metrics['trades_closed']
            
            # Average profit/loss
            won_pnl = won.get('pnl', {})
            lost_pnl = lost.get('pnl', {})
            
            metrics['avg_money_winning'] = won_pnl.get('average')
            metrics['avg_money_losing'] = lost_pnl.get('average')
            metrics['best_winning_trade'] = won_pnl.get('max')
            metrics['worst_losing_trade'] = lost_pnl.get('max')
            
            # Average trade duration
            len_info = trade_analysis.get('len', {})
            if isinstance(len_info, dict):
                total_len = len_info.get('total', {})
                if isinstance(total_len, dict):
                    metrics['avg_trade_duration'] = total_len.get('average')
        
        return metrics
    
    def get_kpi_metrics(self):
        """Get key performance indicators.
        
        Returns:
            dict: KPI metrics dictionary
        """
        metrics = {
            'sharpe_ratio': None,
            'sqn_score': None,
            'sqn_human': None,
            'sortino_ratio': None,
        }
        
        # Sharpe ratio
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
        
        # Sortino ratio
        sortino = self._get_analyzer_result('sortinoratio')
        if sortino:
            metrics['sortino_ratio'] = sortino.get('sortinoratio')
        
        return metrics
    
    def get_equity_curve(self):
        """Get equity curve data.
        
        Returns:
            tuple: (dates, values) Lists of dates and equity values
        """
        try:
            import pandas as pd
        except ImportError:
            return None, None
        
        dates = []
        values = []
        
        # Try to get from Broker observer
        if hasattr(self.strategy, 'observers'):
            for obs in self.strategy.observers:
                if obs.__class__.__name__ == 'Broker':
                    if hasattr(obs.lines, 'value'):
                        value_line = obs.lines.value
                        length = len(value_line)
                        
                        # Get dates
                        if hasattr(self.strategy, 'data'):
                            data = self.strategy.data
                            from ..utils.date import num2date
                            # Correct indexing: from 1-length to 0
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
            # Try to get from TimeReturn analyzer and calculate cumulative equity
            time_return = self._get_analyzer_result('timereturn')
            if time_return:
                start_cash = self._get_start_cash() or 100000
                cumulative_value = start_cash
                for dt, ret in sorted(time_return.items()):
                    cumulative_value = cumulative_value * (1 + ret)
                    dates.append(dt)
                    values.append(cumulative_value)
        
        if not values:
            # If still no data, calculate buy-and-hold equity curve from data source as fallback
            benchmark_dates, benchmark_values = self.get_buynhold_curve()
            if benchmark_dates and benchmark_values:
                start_cash = self._get_start_cash() or 100000
                dates = benchmark_dates
                # Convert normalized values to actual equity values
                values = [start_cash * v / 100 for v in benchmark_values]
        
        return dates, values
    
    def get_buynhold_curve(self):
        """Get buy-and-hold comparison curve.
        
        Returns:
            tuple: (dates, values) Lists of dates and buy-and-hold values
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
            
            # Get open price as buy-and-hold benchmark
            first_price = None
            
            from ..utils.date import num2date
            
            # Correct indexing: from 1-length to 0
            for i in range(length):
                idx = 1 - length + i
                try:
                    dt_num = data.datetime[idx]
                    dates.append(num2date(dt_num))
                    
                    price = data.open[idx]
                    if first_price is None:
                        first_price = price
                    
                    # Normalize to 100
                    values.append(100 * price / first_price if first_price else 100)
                except Exception:
                    pass
        except Exception:
            pass
        
        return dates, values
    
    @staticmethod
    def sqn_to_rating(sqn_score):
        """Convert SQN score to human-readable rating.
        
        Reference: http://www.vantharp.com/tharp-concepts/sqn.asp
        
        Args:
            sqn_score: SQN score
            
        Returns:
            str: Human-readable rating
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
        """Get starting cash."""
        if self._broker:
            return getattr(self._broker, 'startingcash', None)
        return None
    
    def _get_end_value(self):
        """Get final portfolio value."""
        if self._broker:
            return self._broker.getvalue()
        return None
    
    def _get_backtest_days(self):
        """Get number of backtest days."""
        if not hasattr(self.strategy, 'data'):
            return None
        
        data = self.strategy.data
        try:
            from ..utils.date import num2date
            
            length = len(data)
            if length < 2:
                return None
            
            # Correct indexing: 0 is current (last) bar, 1-length is first bar
            start_dt = num2date(data.datetime[1 - length])
            end_dt = num2date(data.datetime[0])
            
            delta = end_dt - start_dt
            return delta.days
        except Exception:
            return None
    
    def _get_analyzer_result(self, name):
        """Get analyzer result.
        
        Args:
            name: Analyzer name (case-insensitive)
            
        Returns:
            dict: Analyzer result, or None if not found
        """
        if self._analyzers is None:
            return None
        
        # Try to get directly by name
        name_lower = name.lower()
        
        # Iterate through all analyzers
        for analyzer in self._analyzers:
            analyzer_name = analyzer.__class__.__name__.lower()
            
            # Check name match
            if analyzer_name == name_lower or name_lower in analyzer_name:
                try:
                    return analyzer.get_analysis()
                except Exception:
                    pass
            
            # Check _name attribute
            custom_name = getattr(analyzer, '_name', '').lower()
            if name_lower in custom_name:
                try:
                    return analyzer.get_analysis()
                except Exception:
                    pass
        
        return None
    
    def get_strategy_info(self):
        """Get strategy information.
        
        Returns:
            dict: Strategy information dictionary
        """
        info = {
            'strategy_name': self.strategy.__class__.__name__,
            'params': {},
        }
        
        # Get strategy parameters
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
        """Get data information.
        
        Returns:
            dict: Data information dictionary
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
        
        # Data name
        info['data_name'] = getattr(data, '_name', None) or 'Data'
        
        try:
            from ..utils.date import num2date
            
            length = len(data)
            info['bars'] = length
            
            if length > 0:
                # Correct indexing: 0 is current (last) bar, 1-length is first bar
                info['start_date'] = num2date(data.datetime[1 - length])
                info['end_date'] = num2date(data.datetime[0])
        except Exception:
            pass
        
        return info
